# PC Doctor Bugfix Batch — Design

## Overview

This document formalizes the fix approach for six confirmed bug groups in the PC Doctor
desktop application (Tauri + FastAPI backend + vanilla JS). The bugs cover: (1) missing
UI controls in the Control Center SHCE tabs, (2) a broken dynamic installer flow in
Dev Tools, (3) AI Terminal "No response from model" errors caused by blocking I/O and
poor error propagation, (4) EPIPE error dialogs leaking to the user, (5) low-FPS
scrolling from excessive `backdrop-filter` use in CSS, and (6) duplicate event-handler
registrations and shadowed function definitions. Each fix is minimal and surgical:
only the identified defective code paths are changed; all unaffected features remain
identical.

---

## Glossary

- **Bug_Condition (C)**: A predicate over inputs/state that identifies when a specific
  defect is triggered.
- **Property (P)**: The desired output or side-effect when the bug condition holds after
  the fix is applied.
- **Preservation (¬C)**: All inputs/states that do NOT satisfy the bug condition; these
  must produce unchanged results before and after the fix.
- **isBugCondition(X)**: Pseudocode function that returns `true` when input X would
  trigger the identified defect.
- **expectedBehavior(result)**: Pseudocode function that returns `true` when `result`
  satisfies the required correct behavior.
- **F**: Original (unfixed) function or code path.
- **F'**: Fixed function or code path.
- **SHCE**: Self-Healing Core Engine — the Control Center backend/UI subsystem.
- **loadSHCEErrors()**: Frontend function in `main.js` (~line 4768) that renders the
  Error Monitor tab.
- **loadSHCEQueue()**: Frontend function in `main.js` (~line 4648) that renders the
  Repair Queue tab.
- **confirmRun()**: Modal confirmation function in `main.js` (~line 3766) that executes
  a pending command and calls `refreshActiveView()`.
- **DEV_TOOLS**: Constant array in `main.js` (~line 2100) listing known developer tools.
- **ask_ollama()**: Synchronous function in `ai_assistant.py` that sends prompts to
  Ollama; called from async FastAPI routes in `routes_ai.py`.
- **installBridge()**: IIFE in `main.js` (~line 159) that patches `window.fetch` to
  route API calls through Tauri's `fetch_api` Rust command.


---

## Bug Details

### Bug Condition

The batch covers six independent bug conditions across the codebase. Each is
formalized below.

---

#### C1 — Control Center Tab UI Gaps

The bug manifests in three related rendering defects in the SHCE Control Center.

**Formal Specification:**
```
FUNCTION isBugCondition_C1(context)
  INPUT: context = { tab, entryType, cardData }
  OUTPUT: boolean

  RETURN (context.tab === "errors"
          AND NOT entryCardHasQueueFixButton(context.entryType))
      OR (context.tab === "errors"
          AND NOT sectionHeaderHasClearResolvedButton())
      OR (context.tab === "queue"
          AND selectedCandidateIsReadOnly(context.cardData))
END FUNCTION
```

**Examples:**
- Error #12 (resolved outcome) renders with no "Queue Fix" button and uses `.shce-error-entry` instead of `.shce-queue-card` — actual vs expected.
- Error Monitor section header has no bulk-action button — confirmed from `loadSHCEErrors()` source (~line 4768): no header controls rendered.
- Repair Queue card for item #5 shows `selected_candidate` in a read-only `<code>` block with no textarea or "Change Command" button — confirmed from queue card template (~line 4667).

---

#### C2 — Dev Tools Dynamic Installer Falls Back to Wrong Tool Entry

The bug manifests when `confirmRun()` succeeds for a dynamically searched tool that
is not Poetry or pnpm.

**Formal Specification:**
```
FUNCTION isBugCondition_C2(installContext)
  INPUT: installContext = { pendingCommand, DEV_TOOLS }
  OUTPUT: boolean

  installedApp := pendingCommand.affects.toLowerCase()
  RETURN installContext.pendingCommand.affects IS NOT NULL
         AND NOT DEV_TOOLS.some(t => t.name.toLowerCase() === installedApp)
         AND installedApp NOT IN ["poetry", "pnpm"]
END FUNCTION
```

**Examples:**
- User searches "htop" in Dev Tools, runs install, `pendingCommand.affects` = "htop". The `if` block in `confirmRun()` (~line 3857) falls to the generic `else` branch, assigns `icon = "Po"` and `name = "Poetry"` — wrong entry added.
- User searches "gh" (GitHub CLI). Same else branch fires, tool appears as "Poetry" in the installed section.

---

#### C3 — AI Terminal "No Response from Model" / Event-Loop Block

The bug manifests on two separate code paths in `routes_ai.py` and `main.js`.

**Formal Specification:**
```
FUNCTION isBugCondition_C3(request)
  INPUT: request = { endpoint, ollamaState }
  OUTPUT: boolean

  RETURN (request.endpoint IN ["/api/ai", "/api/ai_agent"]
          AND ask_ollama_is_called_synchronously_in_async_handler())
      OR (_ask_ollama_http_returns_None()
          AND cli_fallback_also_fails()
          AND returned_value IN [None, ""])
      OR (request.endpoint === "/api/ai_agent"
          AND d.response IN [null, undefined, ""])
END FUNCTION
```

**Examples:**
- `ai_agent()` route handler calls `ask_ollama(...)` directly (no `run_in_executor`). With a 120 s timeout, all other HTTP requests stall during inference — confirmed in `routes_ai.py` lines ~50 and ~107.
- `_ask_ollama_http()` catches `requests.RequestException` and returns `None`. CLI fallback path not present. `ask_ollama()` returns empty string. Frontend: `d.response || "No response from model."` — generic message, no detail.
- `main.js` line 3597: `const raw = d.response || "No response from model."` — no check for `d.ok === false`, no retry button.


---

#### C4 — EPIPE Errors Shown to User

The bug manifests when the Tauri IPC path (`installBridge`/`ipcFetch`) throws before
the outer `catch` in the `window.fetch` intercept can swallow it.

**Formal Specification:**
```
FUNCTION isBugCondition_C4(error)
  INPUT: error = { message, code, errno }
  OUTPUT: boolean

  errorMsg := error.message.toLowerCase()
  RETURN (errorMsg.includes("epipe")
          OR errorMsg.includes("eio")
          OR errorMsg.includes("econnreset"))
         AND error_originates_inside_ipcFetch_before_outer_catch()
END FUNCTION
```

**Examples:**
- Tauri `fetch_api` Rust command propagates EPIPE mid-response. `ipcFetch` inner catch returns `{ok:false}`, but the outer `window.fetch` intercept's `catch(err)` re-throws, reaching the global error dialog — confirmed from `installBridge()` (~line 230).
- FastAPI receives request on broken pipe; logs `BrokenPipeError` traceback to stderr.

---

#### C5 — Low FPS Scrolling from Excessive `backdrop-filter`

The bug manifests whenever the active view contains `.action-btn`, `.quiet-btn`,
`.search-input`, or `.module-card` elements.

**Formal Specification:**
```
FUNCTION isBugCondition_C5(element)
  INPUT: element = { cssClass, backdropFilterValue, position }
  OUTPUT: boolean

  RETURN (element.cssClass IN [".action-btn", ".quiet-btn", ".search-input"]
          AND has_backdrop_filter(element))
      OR (element.cssClass === ".module-card"
          AND backdrop_filter_blur_radius(element) > 4)
      OR (element.cssClass IN [".view", ".card-grid > *"]
          AND NOT has_scroll_performance_hints(element))
END FUNCTION
```

**Examples:**
- `style.css` applies `backdrop-filter: blur(8px)` to `.action-btn` — each button creates a separate compositing layer on WebKitGTK.
- `.module-card` has `backdrop-filter: blur(8px) saturate(140%)` — halving blur radius to 4px reduces GPU cost significantly.
- `.view` has no `will-change`, `.card-grid > *` has no `content-visibility: auto`.

---

#### C6 — Duplicate Event Handlers and Shadowed Functions

The bug manifests at page load and at modal confirmation time.

**Formal Specification:**
```
FUNCTION isBugCondition_C6(pageState)
  INPUT: pageState = { listeners, globals, functionDeclarations }
  OUTPUT: boolean

  RETURN count_of(pageState.listeners, "unhandledrejection") > 1
      OR count_of_assignments(pageState.globals, "window.toggleOllamaService") > 1
      OR count_of_assignments(pageState.globals, "window.checkOllamaServiceStatus") > 1
      OR count_of_assignments(pageState.globals, "window.loadSHCEQueue") > 1
      OR count_of_assignments(pageState.globals, "window.loadSHCEErrors") > 1
      OR count_of_assignments(pageState.globals, "window.switchSHCETab") > 1
      OR (hoisted_declaration_of("refreshActiveView", sync_version)
          shadows_async_declaration_of("refreshActiveView"))
      OR setInterval_called_for_ollamaStatus_more_than_once_per_navigation()
END FUNCTION
```

**Examples:**
- `window.addEventListener('unhandledrejection', ...)` appears at line ~84 (inside debug IIFE) and line ~113 (global scope) — every unhandled rejection is processed twice.
- `window.toggleOllamaService` assigned twice consecutively at ~line 4490; `window.checkOllamaServiceStatus` assigned twice at ~line 4491; `window.loadSHCEQueue` and `window.loadSHCEErrors` assigned twice at ~lines 5014–5015; `window.switchSHCETab` assigned twice at ~line 5019.
- `function refreshActiveView()` (sync, ~line 3753) is declared after `async function refreshActiveView()` (~line 2143). In JS, the later declaration wins at runtime. `confirmRun()` at line 3920 calls `refreshActiveView()` but gets the sync version that does not handle `os-adaptation` view.
- `setInterval(checkOllamaServiceStatus, 4000)` is guarded by `if (!ollamaStatusInterval)` at ~line 1002 — no duplicate currently, but the structure leaves risk; the intent is to make the guard authoritative.


---

## Expected Behavior

### Preservation Requirements

**Unchanged Behaviors:**

- Overview tab continues to load via `loadSHCEDashboard()` without change (req 3.1).
- Repair Queue approve/reject buttons continue to call `POST /api/shce/approve/{id}` and `POST /api/shce/reject/{id}` (req 3.2, 3.3).
- Individual error log deletion via `DELETE /api/shce/error-log/{id}` continues to work; pending entries continue to be blocked with HTTP 400 (req 3.4, 3.5).
- Static DEV_TOOLS installs (Python, Node.js, Git, etc.) continue to refresh the card grid correctly (req 3.6).
- When Ollama is running and a model is available, the AI terminal continues to return valid text responses (req 3.7).
- When `d.response` contains content, the frontend continues to render it and extract command blocks (req 3.8).
- EPIPE/ECONNRESET errors outside the Tauri IPC path continue to be suppressed by the global `unhandledrejection` and `window.onerror` shields (req 3.9).
- `backdrop-filter` on `.sidebar` and `.topbar` remains unchanged (req 3.10).
- Navigating away from AI Terminal continues to clear the Ollama status poll interval (req 3.11).
- Non-network unhandled rejections continue to be logged to console without a native dialog (req 3.12).
- `confirmRun()` success continues to show a toast, close the modal, and trigger a view refresh (req 3.13).
- Knowledge Base, History, and Environment SHCE tabs continue to lazy-load correctly (req 3.14).

**Scope:**
All code paths not explicitly modified by this fix batch are completely unaffected.
The fix changes are limited to:
- `frontend/main.js`: `loadSHCEErrors()`, `loadSHCEQueue()`, `confirmRun()`, the duplicate global assignments, the sync `refreshActiveView()` near line 3753, and the `installBridge()` fetch intercept error rethrow.
- `backend/routes_ai.py`: `ai_chat()` and `ai_agent()` route handlers (add `run_in_executor`).
- `backend/routes_shce.py`: new `DELETE /api/shce/error-log/bulk-resolved` route and new `PATCH /api/shce/queue/{queue_id}/command` route.
- `backend/ai_assistant.py`: `ask_ollama()` fallback return string when both HTTP and CLI fail.
- `frontend/style.css`: remove `backdrop-filter` from `.action-btn`, `.quiet-btn`, `.search-input`; reduce blur on `.module-card`; add scroll-performance hints.


---

## Hypothesized Root Cause

### C1 — Control Center Tab UI Gaps

1. **Missing card template parity**: `loadSHCEErrors()` uses a custom `.shce-error-entry` div that was written independently of the queue card template; no one ported the "Queue Fix" button or header controls.
2. **No bulk-delete endpoint existed**: The backend `routes_shce.py` had no `DELETE /api/shce/error-log/bulk-resolved` route, so no "Clear Resolved" button was ever wired up.
3. **Selected-candidate was treated as read-only data**: The queue card template renders `bestCmd` inside a `<code>` block with no intent to edit — the editable textarea and PATCH route were simply never implemented.

### C2 — Dev Tools Dynamic Installer

1. **Name-based special casing instead of data-driven lookup**: The `if/else if/else` block in `confirmRun()` (~line 3860) hard-codes Poetry and pnpm checks; any other tool name falls to the else branch that incorrectly initialises `icon = "Po"` and `name = "Poetry"` before the generic overrides, leaving description missing.
2. **`btn.dataset.appName` already holds the correct name**: The `extractDynamicCommand()` function sets `btn.dataset.appName = appName` (~line 2304), but `confirmRun()` reads `pendingCommand.affects` which was set from `btn.dataset.appName` via `openModal()` — the correct value is available; the issue is how the new DEV_TOOLS entry is constructed.

### C3 — AI Terminal / Ollama Blocking

1. **Synchronous blocking call in async handler**: `ask_ollama()` uses `requests.post(..., timeout=120)` — a blocking call inside an `async def` FastAPI route with no `run_in_executor`, starving the uvicorn event loop.
2. **Silent None propagation**: `_ask_ollama_http()` returns `None` on `requests.RequestException`; `ask_ollama()` then falls through to CLI, but if CLI is unavailable it returns an empty string. No descriptive error string is built.
3. **Frontend collapses all empty responses**: Line 3597 `d.response || "No response from model."` treats network errors, model errors, and genuine empty replies identically.

### C4 — EPIPE Errors

1. **`window.fetch` intercept re-throws in its own catch**: The outer `catch(err)` in `installBridge()` (~line 229) calls `throw err` after logging — this bypasses the `ipcFetch` inner catch that already returned a safe `{ok:false}` object, so EPIPE errors that surface as exceptions from `invoke('fetch_api')` are re-thrown rather than absorbed.
2. **FastAPI has no application-level `BrokenPipeError` handler**: Uvicorn logs broken-pipe tracebacks to stderr by default; no middleware suppresses them.

### C5 — Low FPS Scrolling

1. **`backdrop-filter` on inline interactive elements**: Small buttons and inputs do not benefit visually from blur but each creates a GPU compositing layer. On WebKitGTK (Tauri Linux), many such layers reduce scroll FPS significantly.
2. **`backdrop-filter` blur radius 8px on cards**: Larger radius means more GPU fill; 4px halves the cost with negligible visual change.
3. **No scroll-performance hints**: `content-visibility: auto` defers off-screen card rendering; `will-change: transform` promotes the active view to its own layer; `-webkit-overflow-scrolling: touch` enables accelerated scrolling in WebKit.

### C6 — Duplicate Handlers / Shadowed Function

1. **Copy-paste during development**: The `unhandledrejection` handler inside the debug IIFE was written before the global shield was added; neither was removed when the other was written.
2. **Consecutive global assignments**: `window.toggleOllamaService`, `window.checkOllamaServiceStatus`, `window.loadSHCEQueue`, `window.loadSHCEErrors`, and `window.switchSHCETab` all have duplicate assignment lines in the same scope — likely a merge artifact.
3. **Declaration order causes shadowing**: In non-strict JS, a later `function refreshActiveView()` declaration replaces an earlier one at runtime. The async version at ~line 2143 handles `os-adaptation` and awaits sub-loaders; the sync version at ~line 3753 does not. `confirmRun()` at ~line 3920 calls the name after both declarations, so it always gets the sync version.


---

## Correctness Properties

Property 1: Bug Condition — Control Center Tab UI Completeness

_For any_ SHCE tab render where the Error Monitor tab is active, the fixed
`loadSHCEErrors()` SHALL render every entry using the same card class and header
structure as `loadSHCEQueue()` entries AND include a "Queue Fix" button; the section
header SHALL include a "Clear Resolved" bulk-action button. For any Repair Queue card,
the fixed template SHALL render an editable `<textarea>` pre-filled with
`selected_candidate` and a "Change Command" button that PATCHes
`/api/shce/queue/{id}/command`.

**Validates: Requirements 2.1, 2.2, 2.3**

---

Property 2: Bug Condition — Dynamic Installer Tool Entry Accuracy

_For any_ successful `confirmRun()` call where `pendingCommand.affects` is set to a
tool name not already in `DEV_TOOLS`, the fixed code SHALL construct the new
`DEV_TOOLS` entry using `btn.dataset.appName` for the display name, derive `icon` from
the first two characters of that name, set `statusKey` to the lowercased name, and push
it to `DEV_TOOLS` — regardless of whether the name is "poetry", "pnpm", or any other
value — then call `loadDevToolCards(true)`.

**Validates: Requirement 2.4**

---

Property 3: Bug Condition — Non-Blocking Ollama I/O

_For any_ POST request to `/api/ai` or `/api/ai_agent`, the fixed route handlers SHALL
call `ask_ollama()` via `asyncio.get_event_loop().run_in_executor(None, ...)`, ensuring
the event loop is not blocked during the up-to-120 s inference window. Concurrent
requests to other endpoints SHALL receive responses without stalling.

**Validates: Requirement 2.5**

---

Property 4: Bug Condition — Meaningful Ollama Error Messages

_For any_ call to `ask_ollama()` where `_ask_ollama_http()` returns `None` AND the CLI
fallback is unavailable or also fails, the fixed `ask_ollama()` SHALL return a
non-empty descriptive error string (e.g., "Ollama did not return a response. The model
may have timed out or crashed.") so the frontend can display an actionable message.

**Validates: Requirement 2.6**

---

Property 5: Bug Condition — AI Terminal Error Discrimination

_For any_ JSON response `d` from `/api/ai_agent` where `d.ok === false`, the fixed
frontend SHALL display `d.detail || d.error` as the error message. When `d.ok` is
truthy but `d.response` is empty, the fixed frontend SHALL display "Model returned no
output" and show a retry button rather than "No response from model."

**Validates: Requirement 2.7**

---

Property 6: Bug Condition — EPIPE Absorbed Before Rethrow

_For any_ error thrown inside `ipcFetch` whose message includes "epipe", "eio", or
"econnreset", the fixed `window.fetch` intercept SHALL catch it in its own try/catch
and return a synthetic `{ok: false, status: 0, bodyJson: {ok: false}}` response object
instead of rethrowing, preventing the error from reaching the global error dialog.

**Validates: Requirement 2.8**

---

Property 7: Bug Condition — Backend Broken-Pipe Silence

_For any_ `BrokenPipeError` or `ConnectionResetError` caught at the FastAPI application
level, the fixed backend SHALL respond with HTTP 503 without writing a traceback to
stderr.

**Validates: Requirement 2.9**

---

Property 8: Bug Condition — No `backdrop-filter` on Inline Controls

_For any_ rendered `.action-btn`, `.quiet-btn`, or `.search-input` element, the fixed
CSS SHALL NOT apply any `backdrop-filter` property, eliminating unnecessary compositing
layers.

**Validates: Requirement 2.10**

---

Property 9: Bug Condition — Reduced `backdrop-filter` on Cards

_For any_ rendered `.module-card` element, the fixed CSS SHALL apply
`backdrop-filter: blur(4px)` (reduced from 8px), halving GPU compositing cost while
retaining the frosted-glass aesthetic.

**Validates: Requirement 2.11**

---

Property 10: Bug Condition — Scroll Performance Hints Applied

_For any_ active view render, the fixed CSS SHALL apply `will-change: transform` to
`.view.active`, `content-visibility: auto` with `contain-intrinsic-size` to
`.card-grid > *`, and `-webkit-overflow-scrolling: touch` to `.view`.

**Validates: Requirement 2.12**

---

Property 11: Bug Condition — Single `unhandledrejection` Registration

_For any_ page load, the fixed `main.js` SHALL register `unhandledrejection` exactly
once in the global scope; the duplicate inside the debug IIFE SHALL be removed.

**Validates: Requirement 2.13**

---

Property 12: Bug Condition — Single Global Assignment per Window Symbol

_For any_ page load, each of `window.toggleOllamaService`,
`window.checkOllamaServiceStatus`, `window.loadSHCEQueue`, `window.loadSHCEErrors`, and
`window.switchSHCETab` SHALL be assigned exactly once.

**Validates: Requirement 2.14**

---

Property 13: Bug Condition — `confirmRun()` Uses Async `refreshActiveView()`

_For any_ `confirmRun()` completion, the fixed code SHALL invoke the full async
`refreshActiveView()` (the version that handles `os-adaptation` and awaits sub-loaders);
the shadowing synchronous declaration near line 3753 SHALL be removed.

**Validates: Requirement 2.15**

---

Property 14: Preservation — All Non-Buggy Paths Unchanged

_For any_ input where none of the above bug conditions hold (isBugCondition returns
false for all C1–C6), the fixed code SHALL produce exactly the same observable behavior
as the original code, preserving Overview tab loading, queue approve/reject flows,
individual error log deletion, static DEV_TOOLS installs, valid AI terminal responses,
sidebar/topbar blur, interval cleanup on navigation away from AI Terminal, and all other
behaviors listed in Section "Unchanged Behavior" of `bugfix.md`.

**Validates: Requirements 3.1–3.14**


---

## Fix Implementation

### Changes Required

All changes assume the root cause analysis above is correct.

---

#### Fix C1 — `frontend/main.js` and `backend/routes_shce.py`

**File:** `frontend/main.js`

**Function:** `loadSHCEErrors()` (~line 4768)

**Specific Changes:**
1. **Card class parity**: Replace the `.shce-error-entry` div with the same `.shce-queue-card` / `.shce-queue-card-header` structure used in `loadSHCEQueue()`.
2. **"Queue Fix" button**: Add a "Queue Fix" button to every card that calls `POST /api/shce/queue-from-error/${e.id}` (the route already exists in `routes_shce.py`).
3. **"Clear Resolved" header button**: Add a button to the section header that calls `DELETE /api/shce/error-log/bulk-resolved`.

**Function:** `loadSHCEQueue()` card template (~line 4667)

**Specific Changes:**
4. **Editable textarea**: Replace the read-only `<code>` block for `selected_candidate` with a `<textarea>` pre-filled with `bestCmd`.
5. **"Change Command" button**: Add a button that reads the textarea value and PATCHes `/api/shce/queue/${item.id}/command`.

**File:** `backend/routes_shce.py`

**Specific Changes:**
6. **New route `DELETE /api/shce/error-log/bulk-resolved`**: Deletes all `error_intelligence` rows where `outcome != 'pending'` in a single SQL `DELETE WHERE outcome != 'pending'` statement; returns `{ok: true, removed: N}`.
7. **New route `PATCH /api/shce/queue/{queue_id}/command`**: Accepts `{"command": "..."}`, validates non-empty, updates `shce_queue.selected_candidate`; returns `{ok: true}`.

---

#### Fix C2 — `frontend/main.js`

**File:** `frontend/main.js`

**Function:** `confirmRun()` (~line 3857)

**Specific Changes:**
1. **Data-driven entry construction**: Replace the `if/else if/else` name-comparison block with a single generic path that always uses `btn.dataset.appName` (via `pendingCommand.affects`) for `name`, derives `icon` from `name.slice(0,2)`, and sets `statusKey = installedApp`. Remove the hard-coded Poetry/pnpm special cases (they now fall through the same generic path correctly).
2. **Description field**: Carry `btn.dataset.purpose` into the new DEV_TOOLS entry as `description` so the tool card displays the extracted description.

---

#### Fix C3 — `backend/routes_ai.py` and `backend/ai_assistant.py`

**File:** `backend/routes_ai.py`

**Functions:** `ai_chat()`, `ai_agent()`

**Specific Changes:**
1. **Non-blocking Ollama call**: Wrap the `ask_ollama(...)` call in both handlers with:
   ```python
   import asyncio, functools
   loop = asyncio.get_event_loop()
   response = await loop.run_in_executor(
       None, functools.partial(ask_ollama, prompt, model=request.model, system=system)
   )
   ```

**File:** `backend/ai_assistant.py`

**Function:** `ask_ollama()`

**Specific Changes:**
2. **Descriptive fallback string**: At the final return statement (currently `"Ollama is running, but PC Doctor failed to communicate with the service."`), replace with `"Ollama did not return a response. The model may have timed out or crashed. Check that 'ollama serve' is running and the model is loaded."`.

**File:** `frontend/main.js`

**Function:** `sendMessage()` / AI agent fetch handler (~line 3591)

**Specific Changes:**
3. **Error discrimination**: Replace `const raw = d.response || "No response from model."` with:
   ```js
   let raw;
   if (!r.ok || d.ok === false) {
     raw = d.detail || d.error || "Backend error — check server logs.";
     appendAgentMsg("err", "⚕ agent>", escHtml(raw));
     // early return
   } else if (!d.response) {
     raw = "Model returned no output.";
     // render retry button
   } else {
     raw = d.response;
   }
   ```

---

#### Fix C4 — `frontend/main.js` and `backend/main.py`

**File:** `frontend/main.js`

**Function:** `installBridge()` — `window.fetch` intercept (~line 218)

**Specific Changes:**
1. **Absorb EPIPE before rethrow**: Replace `catch(err) { console.error(...); throw err; }` with:
   ```js
   catch (err) {
     const m = (err?.message || err?.toString() || "").toLowerCase();
     if (m.includes("epipe") || m.includes("eio") || m.includes("econnreset")) {
       console.warn("[PC Doctor] Absorbed IPC pipe error:", m);
       return { ok: false, status: 0, statusText: "IPC Error",
                headers: new Headers(), json: async () => ({ok:false}), text: async () => "" };
     }
     console.error("[Tauri Fetch Intercept] error:", err);
     throw err;
   }
   ```

**File:** `backend/main.py` (or FastAPI app setup)

**Specific Changes:**
2. **Silence BrokenPipeError in middleware**: Add an exception handler:
   ```python
   @app.exception_handler(BrokenPipeError)
   @app.exception_handler(ConnectionResetError)
   async def broken_pipe_handler(request, exc):
       return Response(status_code=503)
   ```

---

#### Fix C5 — `frontend/style.css`

**Specific Changes:**
1. **Remove `backdrop-filter` from inline controls**: In the rules for `.action-btn`, `.quiet-btn`, and `.search-input`, delete or override any `backdrop-filter` property.
2. **Reduce `.module-card` blur**: Change `backdrop-filter: blur(8px) saturate(140%)` to `backdrop-filter: blur(4px) saturate(140%)`.
3. **Add scroll performance hints**:
   - `.view.active { will-change: transform; }`
   - `.view { -webkit-overflow-scrolling: touch; }`
   - `.card-grid > * { content-visibility: auto; contain-intrinsic-size: 0 200px; }`

---

#### Fix C6 — `frontend/main.js`

**Specific Changes:**
1. **Remove duplicate `unhandledrejection` inside debug IIFE**: Delete lines ~84–100 (the `window.addEventListener('unhandledrejection', ...)` block inside the `(function() { ... })()` IIFE). Retain only the global shield at ~line 113.
2. **Remove duplicate global assignments**: Remove the second occurrence of each:
   - `window.toggleOllamaService` (~line 4490, second assignment)
   - `window.checkOllamaServiceStatus` (~line 4491, second assignment)
   - `window.loadSHCEQueue` (~line 5014, second assignment)
   - `window.loadSHCEErrors` (~line 5015, second assignment)
   - `window.switchSHCETab` (~line 5019, second assignment)
3. **Remove shadowing sync `refreshActiveView()`**: Delete the `function refreshActiveView()` declaration at ~line 3753–3765. The `confirmRun()` call at ~line 3920 will then resolve to the async version at ~line 2143. Since `confirmRun()` is itself async and already awaits the fetch, wrapping the trailing `refreshActiveView()` call in `await` is also recommended.
4. **Reinforce Ollama interval guard**: The existing `if (!ollamaStatusInterval)` guard at ~line 1002 is correct; no code change needed beyond confirming the guard is not bypassed by the SHCE `switchView` override.


---

## Testing Strategy

### Validation Approach

Testing follows a two-phase approach: first, run exploratory tests against the UNFIXED
code to surface counterexamples that confirm the root causes. Then apply fixes and run
fix-checking and preservation-checking tests to validate correctness and no regressions.

---

### Exploratory Bug Condition Checking

**Goal**: Surface counterexamples on the UNFIXED code. Confirm or refute root cause
analysis before writing the fix.

**Test Plan**: Use a combination of DOM inspection tests (for C1/C2/C6), Python unit
tests with mock HTTP (for C3), manual request inspection (for C4), FPS measurement (for
C5), and code-search assertions (for C6).

**Test Cases:**

1. **C1-a Error Monitor card structure** (will fail on unfixed code): Mount
   `loadSHCEErrors()` with mocked API data containing a resolved entry; assert that
   a `.shce-queue-card` element is present and a `[data-action="queue-fix"]` button
   exists.

2. **C1-b "Clear Resolved" button** (will fail on unfixed code): Assert that
   `#shce-section-errors` header contains a button whose click handler calls
   `DELETE /api/shce/error-log/bulk-resolved`.

3. **C1-c Editable command in Repair Queue card** (will fail on unfixed code): Mount
   `loadSHCEQueue()` with a pending item; assert that a `<textarea>` and a
   "Change Command" button are present.

4. **C2 Dynamic installer entry construction** (will fail on unfixed code): Set
   `pendingCommand.affects = "htop"`. Call the install-success branch of `confirmRun()`.
   Assert `DEV_TOOLS` contains an entry with `name === "htop"` and `icon === "ht"`.
   On unfixed code, the entry will have `name === "Poetry"`.

5. **C3-a Event-loop block** (will fail on unfixed code): In a test with a mocked
   slow `ask_ollama` (1 s sleep), call `ai_agent()` and simultaneously call a
   lightweight endpoint. Assert the lightweight endpoint responds in < 200 ms. On
   unfixed code it will stall.

6. **C3-b Empty response propagation** (will fail on unfixed code): Mock
   `_ask_ollama_http` to raise `requests.RequestException`. Mock CLI shutil.which to
   return None. Assert `ask_ollama()` returns a non-empty descriptive string. On
   unfixed code it returns `""`.

7. **C4 EPIPE rethrow** (will fail on unfixed code): In a test environment, make
   `window.desktop.ipcFetch` throw an `Error("EPIPE")`. Call `window.fetch(API + "/api/test")`.
   Assert the call returns `{ok: false}` without throwing. On unfixed code it throws.

8. **C5 FPS regression** (informational): Use Chrome DevTools or a Playwright
   `evaluate` to count compositor layers on a view with `.action-btn` elements.
   Assert zero `backdrop-filter` layers on those elements.

9. **C6-a Duplicate listener count** (will fail on unfixed code): After page load,
   count registered `unhandledrejection` listeners. On unfixed code the count is 2.

10. **C6-b refreshActiveView shadowing** (will fail on unfixed code): After page load,
    set `activeViewName = "os-adaptation"`. Call `refreshActiveView()`. Assert it is
    a Promise (async). On unfixed code it returns `undefined` (sync).

**Expected Counterexamples on Unfixed Code:**
- `loadSHCEErrors()` renders `.shce-error-entry` with no Queue Fix button.
- `confirmRun()` adds a "Poetry" entry for any non-Poetry/pnpm tool.
- `ai_agent()` blocks the event loop; empty `ask_ollama()` fallback returns `""`.
- `window.fetch` rethrows EPIPE errors.
- Two `unhandledrejection` listeners present at page load.
- `refreshActiveView()` is synchronous; calling it on `os-adaptation` view does nothing.

---

### Fix Checking

**Goal**: Verify that for all inputs where each bug condition holds, the fixed function
produces the expected behavior.

**Pseudocode:**
```
FOR ALL input WHERE isBugCondition_Cn(input) DO
  result := F'(input)
  ASSERT expectedBehavior_n(result)
END FOR
```

**Test Cases (run on FIXED code):**

1. **C1 queue-card structure**: Confirm `.shce-queue-card` and Queue Fix button present in error entries.
2. **C1 bulk-delete route**: `DELETE /api/shce/error-log/bulk-resolved` removes non-pending rows; returns `{ok: true, removed: N}`.
3. **C1 PATCH command route**: `PATCH /api/shce/queue/1/command` with `{"command": "ls -la"}` updates `selected_candidate`; returns `{ok: true}`.
4. **C2 tool entry**: `confirmRun()` with `affects = "htop"` adds `{name: "htop", icon: "ht", statusKey: "htop"}` to DEV_TOOLS.
5. **C3 non-blocking**: Concurrent lightweight request responds in < 200 ms while `ask_ollama` sleeps 1 s.
6. **C3 error string**: `ask_ollama()` with all fallbacks failing returns non-empty descriptive message.
7. **C3 frontend discrimination**: Response with `d.ok === false` shows `d.detail`; empty `d.response` shows "Model returned no output" with retry button.
8. **C4 EPIPE absorbed**: `window.fetch` with EPIPE-throwing `ipcFetch` returns `{ok: false}` without throwing.
9. **C5 no backdrop-filter on buttons**: `.action-btn` computed style has no `backdrop-filter`.
10. **C5 reduced card blur**: `.module-card` computed `backdrop-filter` matches `blur(4px)`.
11. **C5 scroll hints present**: `.view.active` has `will-change: transform`; `.card-grid > *` has `content-visibility: auto`.
12. **C6 single listener**: One `unhandledrejection` handler registered.
13. **C6 single globals**: Each window symbol assigned exactly once.
14. **C6 async refreshActiveView**: `refreshActiveView()` returns a Promise; handles `os-adaptation`.

---

### Preservation Checking

**Goal**: Verify that for all inputs where the bug conditions do NOT hold, the fixed
code produces the same result as the original code.

**Pseudocode:**
```
FOR ALL input WHERE NOT isBugCondition_Cn(input) DO
  ASSERT F(input) = F'(input)
END FOR
```

**Testing Approach**: Property-based testing is appropriate for the backend routes
(C3) where a broad input domain of prompts and model states should all return consistent
responses. For frontend changes (C1, C2, C6), behavioral equivalence tests covering
all unchanged UI flows are sufficient. CSS changes (C5) are verified by visual
regression or computed style assertions on unchanged elements.

**Test Cases:**

1. **Repair Queue approve/reject** (req 3.2, 3.3): Mock queue items; confirm approve
   calls `POST /api/shce/approve/{id}` and toast shows success. Unchanged.
2. **Static DEV_TOOLS install** (req 3.6): `pendingCommand.affects = "python"` — assert
   `DEV_TOOLS.some(t => t.name === "Python")` was already true, no duplicate pushed.
3. **Valid AI response** (req 3.7, 3.8): Mock `ask_ollama` to return "Hello". Assert
   frontend renders "Hello" and extracts command blocks.
4. **Sidebar/topbar blur preserved** (req 3.10): `.sidebar` and `.topbar` computed
   styles still have `backdrop-filter`.
5. **Interval cleared on navigation** (req 3.11): Navigate away from AI Terminal; assert
   `ollamaStatusInterval` is null.
6. **Non-network rejections logged** (req 3.12): Fire an unhandled rejection with
   reason `new Error("syntax error")`. Assert `console.error` was called and no
   native dialog appeared. Listener fires once (not twice).
7. **SHCE Overview tab** (req 3.1): `switchSHCETab("overview")` calls
   `loadSHCEDashboard()` — unchanged.
8. **Individual error log delete** (req 3.4, 3.5): `DELETE /api/shce/error-log/1` on a
   resolved entry returns `{ok: true}`; on a pending entry returns HTTP 400.

---

### Unit Tests

- Test `DELETE /api/shce/error-log/bulk-resolved` with mixed pending/resolved rows.
- Test `PATCH /api/shce/queue/{id}/command` with valid and empty-string command.
- Test `ask_ollama()` returns descriptive string when both HTTP and CLI fail.
- Test `ai_chat()` and `ai_agent()` are non-blocking (via executor mock).
- Test `loadSHCEErrors()` card HTML structure contains Queue Fix button and correct class.
- Test `confirmRun()` DEV_TOOLS entry for arbitrary tool name.
- Test `refreshActiveView()` resolves to async version and handles `os-adaptation`.
- Test `window.fetch` EPIPE absorption in the Tauri fetch intercept.

### Property-Based Tests

- Generate random tool names (not "poetry"/"pnpm") for `confirmRun()` and verify the
  DEV_TOOLS entry always has `name === affects` and `icon === name.slice(0,2)`.
- Generate random `ask_ollama()` failure scenarios (HTTP error codes, timeouts, CLI
  missing) and verify the returned string is always non-empty.
- Generate random `d.response` values (empty, null, undefined, short string, long
  string) for the AI terminal handler and verify only the three correct code paths are
  taken.
- Generate many `unhandledrejection` events (mix of network and non-network) and verify
  exactly one handler fires and exactly one `event.preventDefault()` call is made for
  each network event.

### Integration Tests

- Full SHCE flow: load Error Monitor tab, verify card structure, click "Queue Fix",
  switch to Repair Queue, verify item appears, edit command via textarea, approve.
- Full Dev Tools flow: search "htop", confirm install, verify "htop" appears in
  installed section with correct name and icon.
- Full AI terminal flow with Ollama running: send message, verify non-blocking (other
  API calls succeed concurrently), verify response renders correctly.
- Full AI terminal flow with Ollama down: verify descriptive error message shown with
  retry button, not "No response from model."
- Scroll performance: navigate to Dev Tools view with many cards; measure compositor
  layer count; confirm `.action-btn` elements have no `backdrop-filter` layer.
- Page load: confirm single `unhandledrejection` listener, confirm async
  `refreshActiveView`, confirm no duplicate window globals.
