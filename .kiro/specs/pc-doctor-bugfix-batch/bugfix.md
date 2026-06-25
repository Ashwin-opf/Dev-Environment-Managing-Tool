# Bugfix Requirements Document

## Introduction

This document captures the requirements for a batch of six confirmed bug groups in the PC Doctor desktop application (Tauri + FastAPI + vanilla JS). The bugs span the Control Center (SHCE) tabs, Dev Tools dynamic install flow, AI Terminal response handling, EPIPE error dialogs, low-FPS scrolling from excessive `backdrop-filter` usage, and code redundancy from duplicate event handlers and variable assignments. Each bug is described in terms of what currently goes wrong, what the correct behaviour should be, and what existing behaviour must be preserved after the fix.

---

## Bug Analysis

### Current Behavior (Defect)

**Bug Group 1 — Control Center Tabs**

1.1 WHEN the user clicks the Error Monitor tab THEN the system renders error entries without a "Queue Fix" button, using a different card style than the Repair Queue entries (no header structure, no matching card class pattern).

1.2 WHEN the user views the Error Monitor tab header (`#shce-section-errors`) THEN the system shows no bulk action controls, leaving no way to delete all resolved/failed entries in a single click.

1.3 WHEN the user views a Repair Queue card THEN the system shows the `selected_candidate` command as read-only code text with no editable input or "Change Command" button, making it impossible to modify the command before approving it.

**Bug Group 2 — Dev Tools Dynamic Installer**

1.4 WHEN the user successfully installs a tool via the dynamic search card (`dynamic-install-btn`) THEN the system only adds Poetry or pnpm to `DEV_TOOLS` by name comparison and falls back to incorrect icon/key guesses for any other tool, so the newly installed tool does not appear in the installed tools section on refresh.

**Bug Group 3 — AI Terminal "No response from model" error**

1.5 WHEN the backend `ask_ollama()` function is called from an `async` FastAPI route handler THEN the system runs it synchronously, blocking the entire event loop during the model inference timeout (up to 120 s), causing other requests to stall.

1.6 WHEN `_ask_ollama_http()` returns `None` due to a `requests.RequestException` AND the CLI fallback also fails THEN the system returns an empty string or `None` as the response, which the frontend maps to the misleading message "No response from model." with no actionable error detail shown to the user.

1.7 WHEN the AI terminal receives a response where `d.response` is an empty string, `null`, or `undefined` THEN the system unconditionally displays "No response from model." without distinguishing between a model error, a backend error, and a genuine empty reply, and offers no retry mechanism.

**Bug Group 4 — EPIPE errors shown to user**

1.8 WHEN the Tauri `fetch_api` Rust command propagates an EPIPE/EIO/ECONNRESET error THEN the system throws it as an exception from inside the `window.fetch` intercept in `installBridge()` before the outer JS error shield can suppress it, causing a visible error dialog.

1.9 WHEN the FastAPI backend receives a request on a broken pipe or reset connection THEN the system logs the `BrokenPipeError` or `ConnectionResetError` to stderr, surfacing noise in logs and potentially triggering frontend error handling.

**Bug Group 5 — Low FPS scrolling**

1.10 WHEN the user scrolls through any view containing `.action-btn`, `.quiet-btn`, or `.search-input` elements THEN the system applies `backdrop-filter: blur(8px)` to each of those small elements, causing unnecessary GPU compositing layers that degrade scroll frame rate on WebKitGTK (Tauri Linux).

1.11 WHEN the user scrolls through a view with `.module-card` elements THEN the system applies `backdrop-filter: blur(8px) saturate(140%)` per card, which at the current radius incurs avoidable GPU cost and reduces scroll FPS.

1.12 WHEN the user scrolls a view containing `.card-grid` children or a `.view` section with `overflow-y: auto` THEN the system does not use `content-visibility`, `will-change`, or `-webkit-overflow-scrolling` hints, leaving scroll performance unoptimised on WebKit-based renderers.

**Bug Group 6 — Duplicate handlers / code redundancy**

1.13 WHEN the page loads THEN the system registers `window.addEventListener('unhandledrejection', ...)` twice — once inside the debug IIFE (line ~84) and once globally (line ~113) — causing every unhandled rejection to be processed by two separate listeners.

1.14 WHEN the page loads THEN the system assigns `window.toggleOllamaService` and `window.checkOllamaServiceStatus` twice each (once near line 4490 and once implicitly through the globals block), and assigns `window.loadSHCEQueue`, `window.loadSHCEErrors`, and `window.switchSHCETab` redundantly.

1.15 WHEN a modal is confirmed via `confirmRun()` THEN the system calls the simple synchronous `refreshActiveView()` defined at line ~3753 — which only calls per-view loaders without awaiting — rather than the full async `refreshActiveView()` at line ~2143, because the simple version shadows the async one at runtime.

1.16 WHEN the user navigates to the AI Terminal view THEN the system calls `ollamaStatusInterval = setInterval(checkOllamaServiceStatus, 4000)` once, but the wrapping `switchView` override in the SHCE block (line ~1002) was previously structured to run the `setInterval` call on a duplicate line, creating a risk of double-interval registration if the guard condition is not evaluated.

---

### Expected Behavior (Correct)

**Bug Group 1 — Control Center Tabs**

2.1 WHEN the user clicks the Error Monitor tab THEN the system SHALL render each error entry using the same card style as Repair Queue entries — matching header structure, card class, and including a "Queue Fix" button that calls `POST /api/shce/queue-from-error/{error_id}` for all entries regardless of outcome.

2.2 WHEN the user views the Error Monitor tab header THEN the system SHALL display a "Clear Resolved" button in the section header; clicking it SHALL call a new backend route `DELETE /api/shce/error-log/bulk-resolved` that deletes all non-pending entries in one request, then refreshes the list.

2.3 WHEN the user views a Repair Queue card THEN the system SHALL render an editable `<textarea>` pre-filled with `selected_candidate`, and a "Change Command" button that PATCHes the new command to `PATCH /api/shce/queue/{queue_id}/command` before re-rendering the card.

**Bug Group 2 — Dev Tools Dynamic Installer**

2.4 WHEN the user successfully installs a tool via the dynamic search card THEN the system SHALL extract the tool name from `btn.dataset.appName`, build a proper `DEV_TOOLS` entry using the correct icon, name, and `statusKey`, push it to `DEV_TOOLS` if not already present, then call `loadDevToolCards(true)` so the tool appears in the installed section.

**Bug Group 3 — AI Terminal**

2.5 WHEN the FastAPI `ai_chat` and `ai_agent` route handlers call `ask_ollama()` THEN the system SHALL run `ask_ollama()` in a thread-pool executor via `asyncio.get_event_loop().run_in_executor(None, ...)` so the event loop is not blocked during inference.

2.6 WHEN `_ask_ollama_http()` returns `None` AND the CLI fallback also fails THEN the system SHALL return a non-empty, descriptive error string (e.g., "Ollama did not return a response. The model may have timed out or crashed.") so the frontend can display a meaningful message.

2.7 WHEN the AI terminal receives a response with `d.ok === false` THEN the system SHALL display `d.detail || d.error` as the error message; WHEN `d.response` is empty but no HTTP error occurred THEN the system SHALL display a specific "Model returned no output" message and show a retry button rather than a generic fallback string.

**Bug Group 4 — EPIPE errors**

2.8 WHEN the `ipcFetch` call inside `installBridge()` throws an error whose message includes "epipe", "eio", or "econnreset" THEN the system SHALL catch it in an additional try/catch and return a synthetic `{ok: false, status: 0, bodyJson: {ok: false}}` response object instead of rethrowing, preventing the error from reaching the global error dialog.

2.9 WHEN the FastAPI backend encounters a `BrokenPipeError` or `ConnectionResetError` at the application level THEN the system SHALL return a 503 response silently without writing the traceback to stderr.

**Bug Group 5 — Low FPS scrolling**

2.10 WHEN the browser paints `.action-btn`, `.quiet-btn`, or `.search-input` elements THEN the system SHALL NOT apply `backdrop-filter` to those elements, eliminating the unnecessary compositing layers on small inline controls.

2.11 WHEN the browser paints `.module-card` elements THEN the system SHALL apply `backdrop-filter: blur(4px)` (reduced from 8px) to halve GPU compositing cost while retaining the frosted-glass aesthetic.

2.12 WHEN the browser renders the active view and its card grid THEN the system SHALL apply `will-change: transform` to `.view.active`, `content-visibility: auto` with `contain-intrinsic-size` to `.card-grid > *`, and `-webkit-overflow-scrolling: touch` to `.view` to improve scroll performance on WebKit.

**Bug Group 6 — Code redundancy**

2.13 WHEN the page loads THEN the system SHALL register `window.addEventListener('unhandledrejection', ...)` exactly once in the global scope; the duplicate registration inside the debug IIFE SHALL be removed.

2.14 WHEN the page loads THEN each of `window.toggleOllamaService`, `window.checkOllamaServiceStatus`, `window.loadSHCEQueue`, `window.loadSHCEErrors`, and `window.switchSHCETab` SHALL be assigned exactly once.

2.15 WHEN `confirmRun()` completes and calls `refreshActiveView()` THEN the system SHALL invoke the full async `refreshActiveView()` function defined at line ~2143; the shadowing simple synchronous version at line ~3753 SHALL be removed.

2.16 WHEN the user navigates to the AI Terminal view THEN the system SHALL start the Ollama status poll interval exactly once, with no duplicate `setInterval` calls.

---

### Unchanged Behavior (Regression Prevention)

3.1 WHEN the user switches to the Overview tab THEN the system SHALL CONTINUE TO load the dashboard data via `loadSHCEDashboard()` without change.

3.2 WHEN the user switches to the Repair Queue tab THEN the system SHALL CONTINUE TO call `loadSHCEQueue()` and render pending repair items, and the Approve and Reject buttons SHALL CONTINUE TO function as before.

3.3 WHEN the user approves a queued fix with a "Safe" or "Caution" safety class THEN the system SHALL CONTINUE TO execute `POST /api/shce/approve/{queue_id}` and show the result toast.

3.4 WHEN the user deletes an individual non-pending error log entry THEN the system SHALL CONTINUE TO call `DELETE /api/shce/error-log/{entry_id}` and the item SHALL be removed from the list.

3.5 WHEN the backend blocks deletion of a pending error log entry THEN the system SHALL CONTINUE TO return HTTP 400 and the frontend SHALL CONTINUE TO show an error toast.

3.6 WHEN the user installs a tool from the static `DEV_TOOLS` list (e.g., Python, Node.js) via `confirmRun()` THEN the system SHALL CONTINUE TO refresh the Dev Tools card grid and show the tool in the installed section.

3.7 WHEN the Ollama server is running and the model is available THEN the AI terminal SHALL CONTINUE TO return a valid text response through the existing `ask_ollama()` path.

3.8 WHEN the user sends a message to the AI terminal and the backend returns `d.response` with content THEN the system SHALL CONTINUE TO render the response and extract command blocks as before.

3.9 WHEN EPIPE/ECONNRESET/ECONNREFUSED errors occur outside the Tauri IPC fetch path THEN the existing global `unhandledrejection` and `window.onerror` shields SHALL CONTINUE TO suppress them.

3.10 WHEN the user scrolls the sidebar, topbar, or other glassmorphism elements THEN the system SHALL CONTINUE TO render `backdrop-filter` on `.sidebar` and `.topbar` as these are fixed-position elements where the blur has clear UX value.

3.11 WHEN the user navigates away from the AI Terminal view THEN the system SHALL CONTINUE TO clear the Ollama status poll interval.

3.12 WHEN unhandled promise rejections that are NOT network/pipe errors occur THEN the system SHALL CONTINUE TO log them to the console without showing a native browser dialog.

3.13 WHEN `confirmRun()` succeeds for a repair recipe THEN the system SHALL CONTINUE TO show a success toast, close the modal, and trigger a view refresh.

3.14 WHEN the user navigates between SHCE tabs (Knowledge Base, History, Environment) THEN the system SHALL CONTINUE TO lazy-load the respective tab content without change.
