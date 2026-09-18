# Stage 2 Execution Pipeline Consolidation — Migration Result

**Date**: September 16, 2026  
**Status**: COMPLETE (Authoritative Pipeline Live, 282/282 Tests Passing)  
**Corpus / Project**: PC Doctor (`c:\Users\srira\.gemini\antigravity\scratch\pc-doc`)

---

## Executive Summary

Stage 2 of the PC Doctor architecture roadmap has been completed successfully. All execution and mutation pathways across the backend have been consolidated into **one single authoritative execution pipeline** orchestrated by `CentralizedExecutionEngine` (`backend/execution_engine.py`).

Every live route, SHCE self-healing fix, agent tool execution, devtools uninstall, and interactive repair now flows strictly through the mandatory 11-step pipeline:
```
REAL USER ACTION -> LIVE ROUTE -> CENTRALIZED EXECUTION ENGINE -> TIER / APPROVAL -> PRIVILEGE -> LIVE SAFETY GATE -> EXECUTION -> VERIFICATION -> RESCAN -> STRUCTURED LOG -> UI REFRESH
```

Baseline integrity has been strictly preserved:
- **Baseline passing tests**: 270 / 270
- **New Stage 2 consolidation tests**: 12 / 12
- **Total passing test suite**: **282 / 282 passed, 0 failed**

---

## 1. Architectural Comparison: BEFORE vs AFTER

```
BEFORE (Fragmented Execution Paths):
  /api/execute-stream ───> RepairEngine.stream_run() ───> subprocess.Popen
  /api/execute ──────────> RepairEngine.run() ──────────> subprocess.run
  /api/devtools/uninstall> subprocess.Popen (direct raw call in routes_system.py)
  AgentOrchestrator ─────> subprocess.run (direct raw call in agent_orchestrator.py)
  SHCEOrchestrator ──────> subprocess.run (in shce_engine.py)
  Verification ──────────> Fragmented ad-hoc exit code / version checks

AFTER (Single Authoritative Execution Pipeline):
  REAL USER ACTION / API ROUTE
            │
            ▼
  CentralizedExecutionEngine (execution_engine.py)
            │
            ├─► 1. Canonical Identity & Recipe Resolution (canonical_store, recipe_resolver)
            ├─► 2. Live Risk & Tier Selection (select_execution_tier: TIER_1 to TIER_3)
            ├─► 3. Fine-Grained Resource Locking (resource_lock_mgr: per-tool & PM mutex)
            ├─► 4. Live Pre-Execution Safety Gate (authoritative_safety.live_pre_execution_gate)
            │      └─ Natural language rejection, destructive blacklist, live disk space (>=2GB)
            ├─► 5. Process / Privilege Isolation (privilege_manager.run_with_elevation / worker)
            │      └─ UAC Exit Code 1223 -> Normalized to USER_DECLINED_ELEVATION
            ├─► 6. Process Execution & Stream Capture (stdout/stderr non-blocking chunks)
            ├─► 7. Result Classification (classify_execution_result)
            ├─► 8. Authoritative Tiered Verification (verification_engine: L1 FAST to L5 FULL)
            │      └─ Transient timeout: retries verification only, NEVER retries mutation!
            ├─► 9. Structured Telemetry Logging (structured_logger: 16 fields, secrets redacted)
            ├─► 10. Real Machine State Rescan (state_refresher.refresh_tool_state)
            └─► 11. Final UI / SSE Payload & Resource Lock Release
```

---

## 2. Migrated Live Routes & Evidence

| Live Route / Entrypoint | File & Handler | Delegated Authoritative Method | Status |
|---|---|---|---|
| `POST /api/execute` | `backend/routes_system.py::execute_command` | `execution_engine.execute_command()` | **MIGRATED** |
| `POST /api/execute-stream` | `backend/routes_system.py::execute_command_stream` | `execution_engine.stream_execute_command()` | **MIGRATED** |
| `POST /api/devtools/uninstall` | `backend/routes_system.py::devtools_uninstall_app` | `execution_engine.execute_command(operation="UNINSTALL")` | **MIGRATED** |
| `POST /api/shce/execute-queued-fix` | `backend/routes_shce.py` via `shce_engine.py::execute_queued_fix` | `execution_engine.execute_command(source="SHCE")` | **MIGRATED** |
| `POST /api/shce/execute-queued-fix-stream`| `backend/routes_shce.py` via `shce_engine.py::stream_execute_queued_fix` | `execution_engine.stream_execute_command(source="SHCE")` | **MIGRATED** |
| Agent Orchestrator Tool Execution | `backend/agent_orchestrator.py::tool_executor_run` | `execution_engine.execute_command(source="AGENT")` | **MIGRATED** |
| AI / RAG Chat Endpoints | `backend/routes_ai.py` | Read-only guidance; cannot spawn mutation subprocesses | **VERIFIED** |
| Legacy `RepairEngine.run()` | `backend/repair_engine.py::run` | `execution_engine.execute_command()` | **ADAPTED** |
| Legacy `RepairEngine.stream_run()` | `backend/repair_engine.py::stream_run` | `execution_engine.stream_execute_command()` | **ADAPTED** |

---

## 3. Protected Legacy Components Status

All protected legacy components have been preserved, adapted, and tested with zero deletions:

1. **`backend/repair_engine.py`**:
   - Preserved all catalog query, translation, and discovery methods (`list_recipes`, `search_recipes`, `get_recipe`, `translate_command`).
   - `run()` and `stream_run()` delegate execution to `CentralizedExecutionEngine`.
   - Maintained elevation mock compatibility for legacy elevation tests.
   - `test_repair_engine.py`: **17/17 passed**.
2. **`backend/safety.py`**:
   - Preserved all existing public API and method signatures (`SafetyLayer.validate`, `_validate_internal`, `explain_block`).
   - Enforces live safety gate check via `authoritative_safety.live_pre_execution_gate` while preserving exact legacy reason strings and container bypass semantics (`_running_in_container()`).
3. **`backend/verifier.py`**:
   - `verifier.check(target, ...)` delegates directly to `verification_engine.verify_tool(target_name_or_id=target, level=VerificationLevel.CONTROLLED)`.
   - Return dictionary preserves legacy keys (`passed`, `target`, `evidence`, `failures`).
4. **`backend/knowledge.db` & `backend/populate_db.py`**:
   - Preserved intact, serving as the trusted local Static DB source.
   - `RepairEngine` and test suites default to `knowledge.db` when no explicit path is given.

---

## 4. Test Suite Execution Results

### Consolidation Suite (`tests/test_execution_pipeline_consolidation.py`)
All 12 mandatory consolidation scenarios pass:
- `test_01_routes_shce_delegates_to_centralized_execution_engine`: **PASSED**
- `test_02_routes_agent_tool_executor_delegates_to_authoritative_engine`: **PASSED**
- `test_03_routes_system_endpoints_reach_centralized_engine`: **PASSED**
- `test_04_ai_rag_cannot_directly_spawn_mutation_processes`: **PASSED**
- `test_05_safety_block_destructive_and_natural_language`: **PASSED**
- `test_06_authoritative_verification_reached_in_production_call_chain`: **PASSED**
- `test_07_verification_timeout_retries_verification_attempt`: **PASSED**
- `test_08_mutation_never_retries_on_repeated_verification_timeout`: **PASSED**
- `test_09_legacy_repair_engine_delegates_to_centralized_engine`: **PASSED**
- `test_10_elevation_uac_cancelled_normalized_to_user_declined_elevation`: **PASSED**
- `test_11_critical_runtime_trace_call_order`: **PASSED**
- `test_12_end_to_end_mvp_git_path_repair_production_pipeline`: **PASSED**

### Full Regression Test Suite (`pytest tests/ -v`)
```
================= 282 passed, 4 warnings in 312.93s (0:05:12) =================
```
- Total test files: 25
- Total tests executed: 282
- Total tests passed: 282 (100%)
- Total tests failed: 0

---

## 5. Critical Runtime Call-Chain Evidence

The call order was verified under test instrumentation (`test_11_critical_runtime_trace_call_order`):
```
[1] ROUTE: Incoming HTTP request received at /api/execute
[2] SAFETY: live_pre_execution_gate dynamically validates command & disk space (>=2.0 GB)
[3] MUTATION: Process execution occurs strictly once
[4] VERIFICATION: verification_engine.verify_tool probes real tool functionality
[5] RESCAN: state_refresher.refresh_tool_state updates live machine state
[6] LOG: structured_logger.log_event persists 16-field record
```
Relative call order assertions confirmed:
- `route_idx < safety_idx` (Route precedes safety evaluation)
- `safety_idx < verif_idx` (Safety precedes verification)
- `verif_idx <= log_idx` (Verification precedes telemetry logging)
- `last_rescan_idx >= verif_idx` (Rescan occurs post-verification)

---

## 6. Real / Test-Lab End-to-End Evidence (Git PATH Repair)

`test_12_end_to_end_mvp_git_path_repair_production_pipeline` validates the full 11-step lifecycle under the production pipeline:
1. **User Action Received**: `/api/execute-stream` for Git PATH missing repair.
2. **Live Route Called**: FastAPI route handler invoked.
3. **Centralized Engine Called**: Routed to `CentralizedExecutionEngine.stream_execute_command`.
4. **Authoritative Safety Executed**: `live_pre_execution_gate` approved command; verified non-destructive.
5. **Tier Evaluated**: Elevated Admin (Tier 3) evaluated.
6. **Privilege Handled**: `PrivilegeManager` invoked with isolated worker payload.
7. **Mutation Executed**: Command executed once with exit code 0.
8. **Verification Executed**: Functional check passed (`VerificationStatus.VERIFIED`).
9. **Rescan Executed**: `refresh_tool_state("git")` called.
10. **Structured Log Created**: Telemetry event logged with status `VERIFIED`.
11. **Final SSE / API Result**: Emitted done payload with `status: "VERIFIED"`, `returncode: 0`.

---

## 7. Explicit Declarations & Checklist

1. **Has PC Doctor been consolidated into one authoritative execution pipeline?**  
   **YES**. Every mutation route and module routes through `CentralizedExecutionEngine`.

2. **Do live routes now use this pipeline?**  
   **YES**. `routes_system.py`, `routes_shce.py`, and `agent_orchestrator.py` all delegate directly.

3. **Does the authoritative safety gate run before every mutation?**  
   **YES**. `authoritative_safety.live_pre_execution_gate` runs unconditionally before any process is spawned.

4. **Are natural-language instructions rejected without spawning a shell?**  
   **YES**. Verified by `test_05` and `test_elevated_worker_rejects_natural_language_command`.

5. **Are dangerous commands blocked without spawning a shell?**  
   **YES**. Verified by `test_05` with 0 subprocess calls.

6. **Does verification run through AuthoritativeVerificationEngine?**  
   **YES**. Level 1 through 5 verification is orchestrated via `verification_engine`.

7. **Does a verification timeout retry only verification and NOT mutation?**  
   **YES**. Verified by `test_07` (1 mutation, 2 verification attempts).

8. **Does a repeated verification timeout fail without a second mutation?**  
   **YES**. Verified by `test_08` (mutation call count strictly 1).

9. **Can legacy routes bypass the authoritative pipeline?**  
   **NO**. `RepairEngine.run` and `stream_run` delegate to `CentralizedExecutionEngine`.

10. **Does elevation cancellation return 1223 / `USER_DECLINED_ELEVATION`?**  
    **YES**. Verified by `test_10` and `test_3_git_uac_cancellation_user_declined_elevation`.

11. **Are all baseline tests passing?**  
    **YES**. 282 / 282 passed.

---

## 8. Remaining Risks / Out-of-Scope Items (Preserved for Subsequent Stages)

The following items remain strictly out-of-scope for Stage 2 as specified in the prompt:
- Controlled trust threshold changes (Stage 3)
- External tier threshold configuration (Stage 3)
- Hard-override evaluation (Stage 3)
- Exact Git executable-path verification (Stage 4)
- Fresh-process PATH reconstruction (Stage 4)
- Dependency-lock integration (Stage 5)
- 75-problem catalog expansion (Stage 5)
- New Rust toolchain support (Stage 5)
