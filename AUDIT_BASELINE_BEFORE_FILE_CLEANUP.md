# AUDIT BASELINE BEFORE FILE CLEANUP

**Date**: 2026-09-15T23:20:00+05:30  
**Environment**: Windows 10.0.26200 x86_64, Python 3.13.7, Node v24.19.0, npm 11.17.0, Rustc 1.98.1  
**Working Directory**: `c:\Users\srira\.gemini\antigravity\scratch\pc-doc`

---

## 1. Test Suite Baseline

Executed: `backend\.venv\Scripts\python.exe -m pytest tests/ -v`

| Metric | Result |
|---|---|
| **Total Tests** | 270 |
| **Passed** | 270 |
| **Failed** | 0 |
| **Skipped** | 0 |
| **Warnings** | 4 (PytestCollectionWarnings on test_lab dataclasses) |
| **Execution Duration** | 263.35s (04:23) |

### Test Breakdown by Module
1. `tests/test_ai.py`: 4 passed
2. `tests/test_ai_provider_architecture.py`: 9 passed
3. `tests/test_auth.py`: 4 passed
4. `tests/test_authoritative_backend.py`: 18 passed
5. `tests/test_command_adaptation.py`: 2 passed
6. `tests/test_dev_environment_detection.py`: 17 passed
7. `tests/test_development_mode.py`: 2 passed
8. `tests/test_devtools_manager.py`: 27 passed
9. `tests/test_elevation_architecture.py`: 16 passed
10. `tests/test_execution_verification_sync.py`: 11 passed
11. `tests/test_fault_injection_lab.py`: 23 passed
12. `tests/test_path_repair_architecture.py`: 16 passed
13. `tests/test_platform_abstraction_contracts.py`: 25 passed
14. `tests/test_problem_coverage_matrix.py`: 4 passed
15. `tests/test_red_team_fixes.py`: 5 passed
16. `tests/test_repair_engine.py`: 17 passed
17. `tests/test_shce.py`: 54 passed
18. `tests/test_tool_detector.py`: 3 passed
19. `tests/test_update_classifier.py`: 3 passed
20. `tests/test_update_stream.py`: 8 passed

---

## 2. Service & Build Baseline

### Backend Startup Status
- **Entry Point**: `backend/main.py`
- **Uvicorn**: Runs on `http://127.0.0.1:8765`
- **Health Endpoint**: `GET /health` -> `{"status": "healthy", "version": "1.0.0", "os": "Windows"}`
- **OpenAPI Schema**: 80 registered routes accessible and valid.

### Frontend Build Status
- **Build Command**: `npm --prefix frontend run build`
- **Result**: `✓ built in 249ms`
- **Output Artifacts**: `dist/index.html` (55.08 kB), `dist/assets/index-DRfXLhDu.css` (23.24 kB)
- **Dev Server**: Vite v5.4.21 ready on `http://localhost:5173/`

### Tauri Framework Status
- **Command**: `npx tauri info`
- **Result**: Valid configuration (`src-tauri/Cargo.toml`, `tauri.conf.json`, `dist` linked to `../frontend/dist`).
