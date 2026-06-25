# Implementation Plan

## Overview

This plan follows the exploratory bugfix workflow for all six confirmed bug groups in the PC Doctor desktop application. Tasks are ordered: explore bugs first (Property 1), preserve baseline behavior (Property 2), implement fixes, then verify. Source files modified: `frontend/main.js`, `frontend/style.css`, `backend/routes_shce.py`, `backend/routes_ai.py`, `backend/ai_assistant.py`, `backend/main.py`.

## Task Dependency Graph

```json
{
  "waves": [
    { "wave": 1, "tasks": ["1"] },
    { "wave": 2, "tasks": ["2"] },
    { "wave": 3, "tasks": ["3.1", "3.2", "3.3", "3.4", "3.5", "3.6", "3.7", "3.8", "3.9", "3.10", "3.11", "3.12", "3.13"] },
    { "wave": 4, "tasks": ["3.14", "3.15"] },
    { "wave": 5, "tasks": ["4"] }
  ]
}
```

Tasks 3.1 through 3.13 are each independent of one another and may be implemented in any order. Tasks 3.14 and 3.15 depend on all of 3.1–3.13 being complete.

## Tasks

- [ ] 1. Write bug condition exploration tests (BEFORE any fix)
  - **Property 1: Bug Condition** - Control Center, Installer, AI Terminal, EPIPE, CSS, Duplicate Handlers
  - **CRITICAL**: These tests MUST FAIL on unfixed code — failure confirms each bug exists
  - **DO NOT attempt to fix the test or the code when it fails**
  - **NOTE**: Tests encode the expected behavior and will validate the fix when they pass after implementation
  - **GOAL**: Surface counterexamples that demonstrate every bug condition
  - **Scoped PBT Approach**: Scope each property to the concrete failing case(s) defined in design.md
  - **C1 — Error Monitor card structure**: Mount `loadSHCEErrors()` with a mocked resolved entry; assert a `.shce-queue-card` element is present and a `[data-action="queue-fix"]` button exists; assert `#shce-section-errors` header contains a bulk "Clear Resolved" button
  - **C1 — Repair Queue editable command**: Mount `loadSHCEQueue()` with a pending item; assert a `<textarea>` pre-filled with `selected_candidate` and a "Change Command" button are present
  - **C2 — Dynamic installer entry**: Set `pendingCommand.affects = "htop"`; call the install-success branch of `confirmRun()`; assert `DEV_TOOLS` contains an entry with `name === "htop"` and `icon === "ht"` (on unfixed code the entry will have `name === "Poetry"`)
  - **C3-a — Event-loop block**: In a test harness, slow `ask_ollama` with a 1 s sleep; call `ai_agent()` and simultaneously call a lightweight endpoint; assert the lightweight endpoint responds in < 200 ms (on unfixed code it stalls)
  - **C3-b — Empty error propagation**: Mock `_ask_ollama_http` to raise `requests.RequestException` and mock CLI `shutil.which` to return `None`; assert `ask_ollama()` returns a non-empty descriptive string (on unfixed code it returns `""`)
  - **C3-c — Frontend error discrimination**: Simulate a response with `d.ok === false`; assert the AI terminal displays `d.detail` or `d.error`, not "No response from model." (on unfixed code the generic string is shown)
  - **C4 — EPIPE rethrow**: Make `window.desktop.ipcFetch` throw `new Error("EPIPE")`; call `window.fetch(API + "/api/test")`; assert the call returns `{ok: false}` without throwing (on unfixed code it throws)
  - **C5 — Backdrop-filter on buttons**: Assert `.action-btn` computed style has no `backdrop-filter`; assert `.module-card` computed `backdrop-filter` is `blur(4px)` (on unfixed code buttons have blur and cards have blur(8px))
  - **C6-a — Duplicate unhandledrejection listener**: After page load, count registered `unhandledrejection` listeners; assert count is 1 (on unfixed code count is 2)
  - **C6-b — refreshActiveView shadowing**: After page load, call `refreshActiveView()`; assert it returns a Promise (on unfixed code it returns `undefined`, i.e. the sync version)
  - Run all tests on UNFIXED code
  - **EXPECTED OUTCOME**: Tests FAIL (this is correct — it proves the bugs exist)
  - Document counterexamples found (e.g., "htop install adds 'Poetry' entry", "ask_ollama returns ''", "EPIPE throws to global handler", "two unhandledrejection listeners registered")
  - Mark task complete when tests are written, run, and failures are documented
  - _Requirements: 1.1, 1.2, 1.3, 1.4, 1.5, 1.6, 1.7, 1.8, 1.9, 1.10, 1.11, 1.12, 1.13, 1.14, 1.15, 1.16_

- [ ] 2. Write preservation property tests (BEFORE implementing fix)
  - **Property 2: Preservation** - All Non-Buggy Paths Unchanged
  - **IMPORTANT**: Follow observation-first methodology — run UNFIXED code with non-buggy inputs, observe actual outputs, then write tests asserting those outputs
  - **Repair Queue approve/reject** (req 3.2, 3.3): Mock queue items; confirm approve calls `POST /api/shce/approve/{id}` and a success toast is shown; confirm reject calls `POST /api/shce/reject/{id}`
  - **Static DEV_TOOLS install** (req 3.6): Call `confirmRun()` with `pendingCommand.affects = "python"`; assert `DEV_TOOLS.some(t => t.name === "Python")` was already true and no duplicate entry is pushed
  - **Valid AI response** (req 3.7, 3.8): Mock `ask_ollama` to return "Hello"; assert frontend renders "Hello" and extracts command blocks as before
  - **Sidebar/topbar blur preserved** (req 3.10): Assert `.sidebar` and `.topbar` computed styles still have `backdrop-filter`
  - **Interval cleared on navigation** (req 3.11): Navigate away from AI Terminal; assert `ollamaStatusInterval` is null
  - **Non-network rejections logged once** (req 3.12): Fire an unhandled rejection with `new Error("syntax error")`; assert `console.error` was called and no native dialog appeared; assert listener fires exactly once
  - **SHCE Overview tab** (req 3.1): Call `switchSHCETab("overview")`; assert `loadSHCEDashboard()` is called — behavior unchanged
  - **Individual error log delete** (req 3.4, 3.5): `DELETE /api/shce/error-log/1` on a resolved entry returns `{ok: true}`; on a pending entry returns HTTP 400
  - **PBT — random non-buggy tool names**: Generate tool names already in `DEV_TOOLS` (e.g., "python", "node", "git"); for each, assert `confirmRun()` does NOT push a duplicate and the existing entry is unchanged
  - **PBT — valid ask_ollama responses**: For random non-empty prompt strings with Ollama mocked as healthy, assert `ask_ollama()` always returns a non-empty string
  - **PBT — unhandledrejection mix**: Generate many rejection events (mix of network and non-network reasons); assert exactly one handler fires per event and exactly one `event.preventDefault()` call is made per network event
  - Run all preservation tests on UNFIXED code
  - **EXPECTED OUTCOME**: Tests PASS (confirms baseline behavior to preserve)
  - Mark task complete when tests are written, run, and passing on unfixed code
  - _Requirements: 3.1, 3.2, 3.3, 3.4, 3.5, 3.6, 3.7, 3.8, 3.9, 3.10, 3.11, 3.12, 3.13, 3.14_

- [ ] 3. Fix PC Doctor bugfix batch

  - [ ] 3.1 Fix C1 — Error Monitor card parity and bulk-delete (`frontend/main.js`, `backend/routes_shce.py`)
    - In `loadSHCEErrors()` (~line 4768): replace `.shce-error-entry` div with the same `.shce-queue-card` / `.shce-queue-card-header` structure used in `loadSHCEQueue()`
    - Add a "Queue Fix" button to every error entry card that calls `POST /api/shce/queue-from-error/${e.id}`
    - Add a "Clear Resolved" button to the `#shce-section-errors` section header that calls `DELETE /api/shce/error-log/bulk-resolved`
    - In `backend/routes_shce.py`: add `DELETE /api/shce/error-log/bulk-resolved` route — deletes all `error_intelligence` rows where `outcome != 'pending'`; returns `{ok: true, removed: N}`
    - _Bug_Condition: isBugCondition_C1(context) where context.tab === "errors" AND NOT entryCardHasQueueFixButton OR NOT sectionHeaderHasClearResolvedButton_
    - _Expected_Behavior: every error entry renders with .shce-queue-card class and Queue Fix button; header renders Clear Resolved button; DELETE route removes all non-pending rows_
    - _Preservation: Overview tab (3.1), approve/reject flows (3.2, 3.3), individual error log deletion (3.4, 3.5), Knowledge Base / History / Environment tabs (3.14) all unchanged_
    - _Requirements: 2.1, 2.2, 3.1, 3.2, 3.3, 3.4, 3.5, 3.14_

  - [ ] 3.2 Fix C1 — Repair Queue editable command and PATCH route (`frontend/main.js`, `backend/routes_shce.py`)
    - In `loadSHCEQueue()` card template (~line 4667): replace read-only `<code>` block for `selected_candidate` with a `<textarea>` pre-filled with `bestCmd`
    - Add a "Change Command" button that reads the textarea value and PATCHes `/api/shce/queue/${item.id}/command`
    - In `backend/routes_shce.py`: add `PATCH /api/shce/queue/{queue_id}/command` route — validates non-empty command, updates `shce_queue.selected_candidate`; returns `{ok: true}`
    - _Bug_Condition: isBugCondition_C1(context) where context.tab === "queue" AND selectedCandidateIsReadOnly(context.cardData)_
    - _Expected_Behavior: Repair Queue card renders editable textarea pre-filled with selected_candidate and a Change Command button that PATCHes the new command_
    - _Preservation: Approve/reject buttons continue to call existing routes (3.2, 3.3); card data load unchanged_
    - _Requirements: 2.3, 3.2, 3.3_

  - [ ] 3.3 Fix C2 — Dynamic installer data-driven DEV_TOOLS entry (`frontend/main.js`)
    - In `confirmRun()` (~line 3857): replace the `if/else if/else` name-comparison block (Poetry/pnpm special cases) with a single generic path
    - Always use `btn.dataset.appName` (via `pendingCommand.affects`) for `name`; derive `icon` from `name.slice(0, 2)`; set `statusKey = installedApp`
    - Carry `btn.dataset.purpose` into the new DEV_TOOLS entry as `description`
    - Push new entry to `DEV_TOOLS` only if not already present, then call `loadDevToolCards(true)`
    - _Bug_Condition: isBugCondition_C2(installContext) where pendingCommand.affects is NOT in DEV_TOOLS AND NOT in ["poetry", "pnpm"]_
    - _Expected_Behavior: DEV_TOOLS entry has name === pendingCommand.affects, icon === name.slice(0,2), statusKey === affects.toLowerCase(), description from btn.dataset.purpose_
    - _Preservation: Static DEV_TOOLS installs (Python, Node.js, Git, etc.) continue to function (3.6); confirmRun success toast and modal close unchanged (3.13)_
    - _Requirements: 2.4, 3.6, 3.13_

  - [ ] 3.4 Fix C3-a — Non-blocking Ollama I/O in async route handlers (`backend/routes_ai.py`)
    - In `ai_chat()` (~line 50): wrap `ask_ollama(...)` call with `asyncio.get_event_loop().run_in_executor(None, functools.partial(ask_ollama, prompt, model=request.model, system=system))`
    - In `ai_agent()` (~line 107): apply the same `run_in_executor` wrapping
    - Add `import asyncio, functools` at the top of `routes_ai.py` if not already present
    - _Bug_Condition: isBugCondition_C3(request) where request.endpoint IN ["/api/ai", "/api/ai_agent"] AND ask_ollama_is_called_synchronously_in_async_handler()_
    - _Expected_Behavior: event loop is not blocked during inference; concurrent requests to other endpoints receive responses without stalling_
    - _Preservation: When Ollama is running and model is available, AI terminal continues to return valid text responses (3.7, 3.8)_
    - _Requirements: 2.5, 3.7, 3.8_

  - [ ] 3.5 Fix C3-b — Descriptive fallback error string (`backend/ai_assistant.py`)
    - In `ask_ollama()`: replace the final fallback return string (currently `"Ollama is running, but PC Doctor failed to communicate with the service."`) with `"Ollama did not return a response. The model may have timed out or crashed. Check that 'ollama serve' is running and the model is loaded."`
    - _Bug_Condition: isBugCondition_C3(request) where _ask_ollama_http_returns_None() AND cli_fallback_also_fails() AND returned_value IN [None, ""]_
    - _Expected_Behavior: ask_ollama() returns a non-empty descriptive error string when all fallbacks fail_
    - _Preservation: When Ollama is healthy, ask_ollama() continues to return the valid model response unchanged (3.7)_
    - _Requirements: 2.6, 3.7_

  - [ ] 3.6 Fix C3-c — AI Terminal frontend error discrimination (`frontend/main.js`)
    - In `sendMessage()` / AI agent fetch handler (~line 3591): replace `const raw = d.response || "No response from model."` with branching logic that checks `r.ok` and `d.ok` first
    - When `!r.ok || d.ok === false`: display `d.detail || d.error || "Backend error — check server logs."` as the error message and return early
    - When `d.ok` is truthy but `d.response` is empty: display "Model returned no output." and show a retry button
    - Otherwise: use `d.response` as `raw` and continue the existing render path
    - _Bug_Condition: isBugCondition_C3(request) where d.response IN [null, undefined, ""]_
    - _Expected_Behavior: d.ok === false shows d.detail/d.error; empty d.response shows "Model returned no output" with retry button_
    - _Preservation: When d.response contains content, frontend continues to render it and extract command blocks (3.8)_
    - _Requirements: 2.7, 3.8_

  - [ ] 3.7 Fix C4 — Absorb EPIPE errors in installBridge fetch intercept (`frontend/main.js`)
    - In `installBridge()` (~line 218): replace `catch(err) { console.error(...); throw err; }` with EPIPE-absorbing logic
    - Check if `(err?.message || err?.toString() || "").toLowerCase()` includes "epipe", "eio", or "econnreset"
    - If yes: log a console warning and return a synthetic `{ ok: false, status: 0, statusText: "IPC Error", headers: new Headers(), json: async () => ({ok:false}), text: async () => "" }` response object
    - If no: re-throw as before
    - _Bug_Condition: isBugCondition_C4(error) where error.message includes "epipe"/"eio"/"econnreset" AND error_originates_inside_ipcFetch_before_outer_catch()_
    - _Expected_Behavior: EPIPE/EIO/ECONNRESET errors inside ipcFetch return {ok: false, status: 0} without throwing_
    - _Preservation: EPIPE/ECONNRESET errors outside the Tauri IPC path continue to be suppressed by the global shields (3.9); non-network rejections continue to be logged to console (3.12)_
    - _Requirements: 2.8, 3.9, 3.12_

  - [ ] 3.8 Fix C4 — Silence BrokenPipeError in FastAPI middleware (`backend/main.py`)
    - Add exception handlers for `BrokenPipeError` and `ConnectionResetError` at the FastAPI application level
    - Each handler returns `Response(status_code=503)` without writing a traceback to stderr
    - Use `@app.exception_handler(BrokenPipeError)` and `@app.exception_handler(ConnectionResetError)` decorators
    - _Bug_Condition: isBugCondition_C4(error) where FastAPI receives request on broken pipe or reset connection_
    - _Expected_Behavior: BrokenPipeError/ConnectionResetError returns HTTP 503 silently with no stderr traceback_
    - _Preservation: Normal request handling and error responses for all other exception types are unchanged_
    - _Requirements: 2.9_

  - [ ] 3.9 Fix C5 — Remove backdrop-filter from inline controls (`frontend/style.css`)
    - In the CSS rules for `.action-btn`, `.quiet-btn`, and `.search-input`: delete or override the `backdrop-filter` property
    - Reduce `.module-card` `backdrop-filter` from `blur(8px) saturate(140%)` to `blur(4px) saturate(140%)`
    - _Bug_Condition: isBugCondition_C5(element) where element.cssClass IN [".action-btn", ".quiet-btn", ".search-input"] AND has_backdrop_filter(element)_
    - _Expected_Behavior: .action-btn/.quiet-btn/.search-input have no backdrop-filter; .module-card uses blur(4px)_
    - _Preservation: .sidebar and .topbar backdrop-filter rules are untouched (3.10)_
    - _Requirements: 2.10, 2.11, 3.10_

  - [ ] 3.10 Fix C5 — Add scroll performance hints (`frontend/style.css`)
    - Add `will-change: transform` to `.view.active`
    - Add `-webkit-overflow-scrolling: touch` to `.view`
    - Add `content-visibility: auto; contain-intrinsic-size: 0 200px;` to `.card-grid > *`
    - _Bug_Condition: isBugCondition_C5(element) where element.cssClass IN [".view", ".card-grid > *"] AND NOT has_scroll_performance_hints(element)_
    - _Expected_Behavior: .view.active has will-change: transform; .card-grid > * has content-visibility: auto; .view has -webkit-overflow-scrolling: touch_
    - _Preservation: All other CSS rules are unchanged; sidebar and topbar rendering unaffected (3.10)_
    - _Requirements: 2.12, 3.10_

  - [ ] 3.11 Fix C6 — Remove duplicate unhandledrejection listener (`frontend/main.js`)
    - Delete the `window.addEventListener('unhandledrejection', ...)` block inside the debug IIFE (~lines 84–100)
    - Retain only the global shield registration (~line 113)
    - _Bug_Condition: isBugCondition_C6(pageState) where count_of(pageState.listeners, "unhandledrejection") > 1_
    - _Expected_Behavior: exactly one unhandledrejection handler registered at page load_
    - _Preservation: Non-network unhandled rejections continue to be logged to console without a native dialog (3.12); network errors continue to be suppressed by the remaining global shield (3.9)_
    - _Requirements: 2.13, 3.9, 3.12_

  - [ ] 3.12 Fix C6 — Remove duplicate window global assignments (`frontend/main.js`)
    - Remove the second assignment of `window.toggleOllamaService` (~line 4490, second occurrence)
    - Remove the second assignment of `window.checkOllamaServiceStatus` (~line 4491, second occurrence)
    - Remove the second assignment of `window.loadSHCEQueue` (~line 5014, second occurrence)
    - Remove the second assignment of `window.loadSHCEErrors` (~line 5015, second occurrence)
    - Remove the second assignment of `window.switchSHCETab` (~line 5019, second occurrence)
    - _Bug_Condition: isBugCondition_C6(pageState) where count_of_assignments(pageState.globals, symbol) > 1 for any of the five symbols_
    - _Expected_Behavior: each window symbol is assigned exactly once_
    - _Preservation: All five functions continue to operate identically at runtime; SHCE tab switching (3.14), Ollama status polling (3.11), and queue/error loading (3.1, 3.2) all unchanged_
    - _Requirements: 2.14, 3.1, 3.2, 3.11, 3.14_

  - [ ] 3.13 Fix C6 — Remove shadowing sync refreshActiveView and reinforce interval guard (`frontend/main.js`)
    - Delete the synchronous `function refreshActiveView()` declaration at ~lines 3753–3765
    - The `confirmRun()` call at ~line 3920 will then resolve to the async version at ~line 2143
    - Add `await` before the `refreshActiveView()` call in `confirmRun()` since `confirmRun()` is already async
    - Confirm the `if (!ollamaStatusInterval)` guard at ~line 1002 is not bypassed by the SHCE `switchView` override (no code change needed if the guard is intact; add explicit guard if missing)
    - _Bug_Condition: isBugCondition_C6(pageState) where hoisted sync refreshActiveView shadows async version OR setInterval called more than once per navigation_
    - _Expected_Behavior: confirmRun() invokes the full async refreshActiveView() that handles os-adaptation and awaits sub-loaders; Ollama status interval starts exactly once per AI Terminal navigation_
    - _Preservation: confirmRun() continues to show success toast, close modal, and trigger refresh (3.13); navigating away from AI Terminal continues to clear the interval (3.11)_
    - _Requirements: 2.15, 2.16, 3.11, 3.13_

  - [ ] 3.14 Verify bug condition exploration tests now pass
    - **Property 1: Expected Behavior** - All Bug Conditions Resolved
    - **IMPORTANT**: Re-run the SAME tests from task 1 — do NOT write new tests
    - The tests from task 1 encode the expected behavior for all six bug conditions
    - When these tests pass, they confirm all expected behaviors are satisfied
    - Re-run the full Property 1 suite from task 1 against fixed code
    - **EXPECTED OUTCOME**: All tests PASS (confirms all six bugs are fixed)
    - _Requirements: 2.1, 2.2, 2.3, 2.4, 2.5, 2.6, 2.7, 2.8, 2.9, 2.10, 2.11, 2.12, 2.13, 2.14, 2.15_

  - [ ] 3.15 Verify preservation tests still pass
    - **Property 2: Preservation** - All Non-Buggy Paths Unchanged
    - **IMPORTANT**: Re-run the SAME tests from task 2 — do NOT write new tests
    - Run the full Property 2 preservation suite from task 2 against fixed code
    - **EXPECTED OUTCOME**: All tests PASS (confirms no regressions introduced)
    - Confirm approve/reject, static installs, valid AI responses, sidebar/topbar blur, interval cleanup, single listener behavior, SHCE tab loading all remain identical
    - _Requirements: 3.1, 3.2, 3.3, 3.4, 3.5, 3.6, 3.7, 3.8, 3.9, 3.10, 3.11, 3.12, 3.13, 3.14_

- [ ] 4. Checkpoint — Ensure all tests pass
  - Run the complete test suite (Property 1 bug condition tests + Property 2 preservation tests + any unit/integration tests written during the fix tasks)
  - Confirm all Property 1 exploration tests PASS on fixed code
  - Confirm all Property 2 preservation tests PASS on fixed code
  - Confirm no new lint errors or type errors introduced in modified files (`frontend/main.js`, `frontend/style.css`, `backend/routes_shce.py`, `backend/routes_ai.py`, `backend/ai_assistant.py`, `backend/main.py`)
  - If any test fails, do NOT proceed — investigate and resolve before marking complete
  - Ask the user if any questions arise during verification

## Notes

- Tasks 1 and 2 must be completed on UNFIXED code before any implementation begins.
- Each fix task (3.1–3.13) targets a distinct bug condition and may be reviewed in isolation.
- The Property 1 exploration tests are expected to FAIL before fixes; they are the acceptance criteria for correctness.
- The Property 2 preservation tests are expected to PASS both before and after fixes; any failure after fixing indicates a regression.
- Backend route additions (3.1, 3.2) require the FastAPI dev server to be restarted to take effect.
- CSS changes (3.9, 3.10) are visually verifiable in the Tauri window; FPS improvement is most noticeable on WebKitGTK (Linux).
