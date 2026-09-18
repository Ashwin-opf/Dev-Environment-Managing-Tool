# EXECUTION PIPELINE MIGRATION MAP

**Date**: 2026-09-15  
**Project**: PC Doctor  
**Status**: Authoritative Call-Graph Mapping for Mutation Routes  

---

## 1. Executive Summary

This document traces the call graphs of all live mutation-capable routes across the PC Doctor codebase. It identifies the legacy execution paths currently used in production routes and defines the target delegation to the single Authoritative Execution Pipeline (`backend/execution_engine.py` / `CentralizedExecutionEngine`).

---

## 2. Live Mutation Routes Audit Table

| Route / Endpoint | Purpose | Orchestrator | Current Execution Implementation | Current Safety Gate | Current Risk & Tier | Current Elevation | Current Verification | Current Result Classifier | Migration Target Status |
|---|---|---|---|---|---|---|---|---|---|
| `POST /api/execute` (`routes_system.py`) | Primary UI repair/install/command mutation | `RepairEngine` (`app_context.py`) | `engine.run(command)` (`repair_engine.py` via `subprocess.run`) | `safety.py` (`SafetyLayer.validate`) | Static risk tag (`Low`/`Medium`/`High`) | `PrivilegeManager` (`privilege_manager.py`) | `dev_environment_detector.post_repair_verify` | Ad-hoc dict mapping | **MIGRATE TO CentralizedExecutionEngine** |
| `POST /api/execute-stream` (`routes_system.py`) | Real-time SSE streaming repair execution | `RepairEngine` (`app_context.py`) | `engine.stream_run(command)` | `safety.py` (`SafetyLayer.validate`) | Static risk tag | `PrivilegeManager` | `dev_environment_detector.post_repair_verify` | `result_classifier.py` | **MIGRATE TO CentralizedExecutionEngine** |
| `POST /api/shce/approve/{queue_id}` (`routes_shce.py`) | Approves and executes queued self-healing remediation | `SHCEOrchestrator` (`shce_engine.py`) | `RepairEngine.run` (`shce_engine.py:2446`) | `SafetyClassificationLayer` (`self_healing.py`) | Static safety classification | `PrivilegeManager` (via `RepairEngine`) | None / command returncode check | None (raw return code) | **MIGRATE TO CentralizedExecutionEngine** |
| `POST /api/shce/stream-approve/{queue_id}` (`routes_shce.py`) | Streaming execution of approved SHCE fix | `SHCEOrchestrator` (`shce_engine.py`) | `RepairEngine.stream_run` (`shce_engine.py:2531`) | `SafetyClassificationLayer` | Static safety classification | `PrivilegeManager` | None / command returncode check | None (raw return code) | **MIGRATE TO CentralizedExecutionEngine** |
| `POST /api/agent/task` (`routes_agent.py`) | High-level agent multi-step goal execution | `AgentOrchestrator` (`agent_orchestrator.py`) | `tool_executor_run` (`subprocess.run` shell=True) | `tool_risk_assess` (`risk_engine.py`) | `risk_engine.py` (ad-hoc) | None (fails if elevated) | `verifier.py` (`verifier_check`) | None (boolean `success`) | **MIGRATE TO CentralizedExecutionEngine** |
| `POST /api/devtools/uninstall` (`routes_system.py`) | Package uninstallation | Direct route | `subprocess.run` in `devtools_manager.py` | `safety.py` | None | `PrivilegeManager` | `dev_environment_detector` | `result_classifier.py` | **MIGRATE TO CentralizedExecutionEngine** |
| `POST /api/system/update-packages` (`routes_system.py`) | System-wide package update | Direct route | `engine.run` (`repair_engine.py`) | `safety.py` | Static Low risk | `PrivilegeManager` | `dev_environment_detector` | `result_classifier.py` | **MIGRATE TO CentralizedExecutionEngine** |
| `POST /api/self-healing/approve` (`routes_system.py`) | Legacy self-healing fix approval | Direct route | `engine.run` (`repair_engine.py`) | `safety.py` | Static | `PrivilegeManager` | `dev_environment_detector` | Ad-hoc | **MIGRATE TO CentralizedExecutionEngine** |
| `POST /api/ai_chat`, `/api/ai_agent` (`routes_ai.py`) | Natural language diagnosis & guidance | AI Provider / Ollama | **NONE (Read-only)**; returns Markdown code blocks | N/A (Prompt safety guidelines) | N/A | N/A | N/A | N/A | **READ-ONLY (Preserve intact)** |

---

## 3. Detailed Call Graphs: Before vs After Migration

### Call Graph 1: `routes_system.py` (`/api/execute` & `/api/execute-stream`)

#### BEFORE Migration:
```
UI Click / API Request
  │
  ▼
routes_system.py:execute_command()
  │
  ├──► safety.py (SafetyLayer.validate) ── [Legacy AST validation]
  │
  ├──► app_context.py (engine = RepairEngine())
  │      │
  │      ├──► repair_engine.py:run() / stream_run()
  │      │      │
  │      │      ├──► privilege_manager.py (if elevate requested)
  │      │      │
  │      │      └──► subprocess.run / Popen (raw shell execution)
  │      │
  │      └──► dev_environment_detector.py:post_repair_verify()
  │
  └──► HTTP JSON / SSE Response
```

#### AFTER Migration:
```
UI Click / API Request
  │
  ▼
routes_system.py:execute_command()
  │
  ▼
backend/execution_engine.py (CentralizedExecutionEngine)
  │
  ├──► canonical_identity.py (resolve canonical identity & action)
  ├──► risk_engine.py (compute dynamic composite risk)
  ├──► execution_tier.py (Tier 1 Auto / Tier 2 User Confirm / Tier 3 Elevated)
  ├──► authoritative_safety.py (live pre-execution safety gate with NL detection)
  ├──► privilege_manager.py (PrivilegeManager elevation if Tier 3)
  ├──► platform_abstraction (OS process runner with real-time stream capture)
  ├──► result_classifier.py (unified semantic classification)
  ├──► verification_engine.py (Authoritative L1-L5 verification with retry policy)
  ├──► structured_logger.py (16-field audit log)
  └──► state_refresh.py (refresh real machine state)
```

---

### Call Graph 2: `routes_shce.py` (`/api/shce/approve/{queue_id}`)

#### BEFORE Migration:
```
POST /api/shce/approve/{id}
  │
  ▼
shce_engine.py:execute_queued_fix()
  │
  ├──► self_healing.py (SafetyClassificationLayer.classify)
  │
  ├──► repair_engine.py:RepairEngine.run() ── [Independent legacy executor]
  │      │
  │      └──► subprocess.run()
  │
  └──► error_intelligence.db update
```

#### AFTER Migration:
```
POST /api/shce/approve/{id}
  │
  ▼
shce_engine.py:execute_queued_fix()
  │
  ├──► CentralizedExecutionEngine.execute_command()
  │      │
  │      ├──► authoritative_safety.py (live safety gate)
  │      ├──► platform_abstraction execution
  │      ├──► verification_engine.py
  │      └──► structured_logger.py
  │
  └──► error_intelligence.db update
```

---

### Call Graph 3: `routes_agent.py` / `agent_orchestrator.py`

#### BEFORE Migration:
```
POST /api/agent/task
  │
  ▼
agent_orchestrator.py:run()
  │
  ├──► tool_executor_run() ──► subprocess.run(shell=True) [Unbounded mutation!]
  │
  └──► tool_verifier_check() ──► verifier.py
```

#### AFTER Migration:
```
POST /api/agent/task
  │
  ▼
agent_orchestrator.py:run()
  │
  ├──► tool_executor_run() ──► CentralizedExecutionEngine.execute_command()
  │                              │
  │                              ├──► authoritative_safety.py
  │                              ├──► execution_tier.py
  │                              ├──► platform_abstraction execution
  │                              └──► verification_engine.py
  │
  └──► tool_verifier_check() ──► verification_engine.py compatibility adapter
```
