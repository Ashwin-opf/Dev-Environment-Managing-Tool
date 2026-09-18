# FILE CLEANUP AUDIT

**Date**: 2026-09-15  
**Project**: PC Doctor  
**Status**: Pre-Cleanup Evidence Matrix & Action Plan  

---

## 1. File Classification Categories

- **`ACTIVE`**: Authoritative, currently in production or targeted architecture, actively tested, actively called.
- **`LEGACY`**: Active but legacy component required by existing live routes or backwards compatibility. Must be retained until controlled migration.
- **`DUPLICATE`**: Overlapping implementation with a confirmed authoritative replacement.
- **`GENERATED`**: Machine-generated build artifact, schema, or manifest.
- **`RUNTIME_STATE`**: Machine-specific runtime state, log, or cache that should not be tracked as source.
- **`TEST_ARTIFACT`**: Test fixture, diagnostic script, or simulation tool.
- **`UNUSED`**: Conclusively unreferenced dead code, orphan file, or obsolete scratch script with zero callers.
- **`UNCERTAIN`**: Ambiguous references; DO NOT DELETE.

---

## 2. Complete Repository File Audit Table

| File / Component | Category | Evidence | Used By | Recommendation | Risk |
|---|---|---|---|---|---|
| `backend/execution_engine.py` | **ACTIVE** | CentralizedExecutionEngine, canonical resolution, dynamic tiering, live pre-execution gate | `test_execution_verification_sync.py`, `test_authoritative_backend.py`, `plan_freeze.py` | **RETAIN** (Primary Authoritative Execution Engine) | None |
| `backend/repair_engine.py` | **LEGACY** | RepairEngine, executes repair recipes, safety check via SafetyLayer | `app_context.py`, `routes_system.py` (`POST /api/execute`), `shce_engine.py`, `test_repair_engine.py` | **RETAIN** (Active Legacy; required for live UI routes) | Critical if deleted |
| `backend/pipeline.py` | **UNUSED** | Zero imports in repository. `PipelineResult` only inside file. `execute_pipeline` unused. | None | **SAFE TO DELETE** | Very Low |
| `backend/authoritative_safety.py` | **ACTIVE** | AuthoritativeSafetyLayer, live pre-execution gate, AST blacklist | `execution_engine.py`, `plan_freeze.py`, `test_authoritative_backend.py` | **RETAIN** (Authoritative Safety Gate) | High if deleted |
| `backend/safety.py` | **LEGACY** | SafetyLayer, natural language detector, subshell extractor | `app_context.py`, `routes_system.py`, `repair_engine.py`, `elevated_worker.py`, `self_healing.py`, tests | **RETAIN** (Active Legacy; required by live routes & tests) | Critical if deleted |
| `backend/risk_engine.py` | **ACTIVE** | Dynamic risk calculation (0-100), side effects, rollback cost | `execution_engine.py`, `pipeline.py`, `agent_orchestrator.py` | **RETAIN** (Authoritative Risk Assessment) | High if deleted |
| `backend/execution_tier.py` | **ACTIVE** | Tier 1 (Auto), Tier 2 (Confirm), Tier 3 (Elevated) selector | `execution_engine.py`, `risk_engine.py`, tests | **RETAIN** (Authoritative Tier Selection) | High if deleted |
| `backend/verification_engine.py` | **ACTIVE** | AuthoritativeVerificationEngine, L1-L5 levels, backoff retry | `execution_engine.py`, `test_execution_verification_sync.py` | **RETAIN** (Authoritative Production Verifier) | High if deleted |
| `backend/verifier.py` | **LEGACY** | Legacy `check(target, expected)` wrapper | `routes_system.py` (L1850), `agent_orchestrator.py` (L34) | **RETAIN** (Active Legacy Verifier) | Medium if deleted |
| `backend/test_lab/verifier.py` | **ACTIVE** | FaultVerifier for simulated fault environments | `test_lab/test_runner.py`, `test_fault_injection_lab.py` | **RETAIN** (Test Lab Verifier) | High if deleted |
| `backend/agent_orchestrator.py` | **ACTIVE** | Agent task planning, memory log, tool execution | `routes_agent.py`, `/api/agent/*` endpoints | **RETAIN** (Active Agent Orchestration) | High if deleted |
| `backend/automation_engine.py` | **ACTIVE** | Dynamic to static solution promotion, idle manager | `test_authoritative_backend.py`, `/api/automation/*` | **RETAIN** (Background Automation) | Medium if deleted |
| `backend/shce_engine.py` | **ACTIVE** | Self-Healing Core Engine, adaptive repair loop | `routes_shce.py`, `test_shce.py` (54 tests) | **RETAIN** (Autonomous Self-Healing) | Critical if deleted |
| `backend/dev_environment_detector.py` | **ACTIVE** | Detects dev runtimes, versions, PATH anomalies, services | `routes_system.py`, `execution_engine.py`, `test_dev_environment_detection.py` | **RETAIN** (Primary Dev Detector) | Critical if deleted |
| `backend/platform_hw.py` | **ACTIVE** | GPU, driver, sensor, and platform query engine | `routes_system.py`, `risk_engine.py`, `test_specs_logic.py` | **RETAIN** (Specialized Hardware Utility) | High if deleted |
| `backend/tool_detector.py` | **ACTIVE** | Heuristic app detector (VSCode, Docker, Ollama) | `routes_system.py`, `routes_ai.py`, `devtools_manager.py`, `test_tool_detector.py` | **RETAIN** (Tool Presence Detector) | High if deleted |
| `backend/adapters/*.py` (12 files) | **ACTIVE** | 12 package manager adapters (`winget`, `apt`, `brew`, `choco`, etc.) | Registered in `adapters/registry.py`, `routes_catalog.py`, `agent_orchestrator.py` | **RETAIN** (Intended Architecture Components) | High if deleted |
| `backend/knowledge_static.db` | **ACTIVE** | 111 classified static recipes, FTS virtual tables (90 KB) | `routes_kb.py`, `recipe_engine.py`, `plan_freeze.py` | **RETAIN** (Primary Static Knowledge Source of Truth) | Critical if deleted |
| `backend/knowledge.db` | **ACTIVE** | 117 recipes, adaptive KB, self-healing attempts (339 KB) | `shce_engine.py`, `repair_engine.py`, `self_healing.py`, `routes_system.py` | **RETAIN** (Primary Self-Healing & Legacy DB) | Critical if deleted |
| `backend/knowledge_dynamic.db` | **ACTIVE** | Dynamic learned solutions, pending approvals (28 KB) | `routes_kb.py`, `automation_engine.py`, `routes_shce.py` | **RETAIN** (Dynamic Learned Knowledge Store) | High if deleted |
| `backend/resolution_cache.db` | **ACTIVE** | Provenance table for package resolution caching (12 KB) | `pkg_resolution.py` (`ProvenanceStore`) | **RETAIN** (Package Resolution Cache) | Medium if deleted |
| `backend/pc_doctor.db` | **UNUSED** | 0 bytes, 0 tables. Listed only in `scripts/inspect_db.py`. | None | **SAFE TO DELETE** | Zero |
| `backend/engine.knowledge.db` | **UNUSED** | 0 bytes, 0 tables. Listed only in `scripts/inspect_db.py`. | None | **SAFE TO DELETE** | Zero |
| `knowledge_static.db` (root) | **UNUSED** | 0 bytes. Misplaced empty file created during root execution. | None | **SAFE TO DELETE** | Zero |
| `knowledge_dynamic.db` (root) | **UNUSED** | 0 bytes. Misplaced empty file created during root execution. | None | **SAFE TO DELETE** | Zero |
| `backend/knowledge_static.db-wal` | **GENERATED** | SQLite WAL file (0 bytes). Temporary transaction artifact. | SQLite runtime engine | **REMOVE & IGNORE** | Zero |
| `backend/knowledge_static.db-shm` | **GENERATED** | SQLite SHM file (32 KB). Temporary shared memory artifact. | SQLite runtime engine | **REMOVE & IGNORE** | Zero |
| `backend/populate_static_db.py` | **ACTIVE** | Comprehensive static catalog populator & synchronizer (111 recipes) | Catalog seeding & synchronization | **RETAIN** (Authoritative Populator) | High if deleted |
| `backend/populate_db.py` | **LEGACY** | Baseline seeder for `knowledge.db` | `scripts/setup.js`, `scripts/setup.ps1`, `scripts/setup.sh` | **RETAIN** (Active Setup Seeder) | High if deleted |
| `scripts/cleanup_db.py` | **UNUSED** | Destructive script deleting static recipes. Zero references. | None | **SAFE TO DELETE** | Zero |
| `backend/test_route.py` | **UNUSED** | 44-line standalone scratch script profiling `psutil.process_iter`. | None | **SAFE TO DELETE** | Zero |
| `backend/devtools_suggest_session.json` | **UNUSED** | Stale test/sample session payload (564 bytes). Zero references. | None | **SAFE TO DELETE** | Zero |
| `frontend/wp_light.jpg` | **ACTIVE** | Light theme wallpaper background image asset | `frontend/main.js` (line 81), `frontend/package.json` | **RETAIN** (Essential Theme Asset) | High if deleted |
| `src-tauri/gen/schemas/*` | **GENERATED** | Tauri v2 generated ACL manifests & capability schemas | Tauri CLI, IDE schema validation | **RETAIN** (Generated Build Metadata) | Low |
| `scripts/create_shortcut.js` | **ACTIVE** | Creates Windows desktop/start shortcuts | `package.json` (`npm run shortcut`) | **RETAIN** | None |
| `scripts/dev.js` | **ACTIVE** | Starts frontend & backend concurrently for development | `package.json` (`npm run dev`) | **RETAIN** | None |
| `scripts/start.js` | **ACTIVE** | Production startup script | `package.json` (`npm run start`), `launch.bat` | **RETAIN** | None |
| `scripts/setup.js`, `.ps1`, `.sh` | **ACTIVE** | Environment setup scripts across platforms | `package.json` (`npm run setup`) | **RETAIN** | None |
| `scripts/launch.bat`, `.vbs`, `.cs` | **ACTIVE** | Windows background launch helpers avoiding console window | Windows shortcut subsystem | **RETAIN** | None |

---

## 3. Concluded Deletion Plan

Based on conclusive evidence showing 0 references across code, tests, configs, and scripts:

1. **Delete Dead Code**:
   - `backend/pipeline.py` (Unreferenced prototype)
   - `backend/test_route.py` (Unreferenced scratch profiling script)
   - `scripts/cleanup_db.py` (Unreferenced destructive scratch script)

2. **Delete 0-byte Orphan Databases**:
   - `knowledge_static.db` (root, 0 bytes)
   - `knowledge_dynamic.db` (root, 0 bytes)
   - `backend/engine.knowledge.db` (backend, 0 bytes)
   - `backend/pc_doctor.db` (backend, 0 bytes)

3. **Clean Transient Runtime & Cache Artifacts**:
   - `backend/devtools_suggest_session.json` (Stale sample payload)
   - `backend/knowledge_static.db-wal` (Temporary SQLite WAL file)
   - `backend/knowledge_static.db-shm` (Temporary SQLite SHM file)
   - Update `.gitignore` to ensure `*.db-wal`, `*.db-shm`, and `*.db-journal` are excluded repository-wide.
