/* ═══════════════════════════════════════════════════════════
   PC Doctor – Frontend Application Logic  v2.0
   ─ AI Terminal Agent (Autonomous)
   ─ Drivers view
   ─ Live Dev-tool status badges
   ─ Communicates with FastAPI backend on port 8765
═══════════════════════════════════════════════════════════ */
const API = "http://127.0.0.1:8765";

// Debug Webview Log Writer
(function() {
  const logFile = "~/Desktop/PC Doc/webview_errors.log";
  let logQueue = [];
  let pendingWriteTimeout = null;

  function sendToRust(msg) {
    try {
      const invoke = window.__TAURI__?.core?.invoke ||
                     window.__TAURI_INTERNALS__?.invoke ||
                     (window.__TAURI__?.tauri?.invoke);
      if (invoke) {
        invoke('log_console', { msg });
      }
    } catch (_) {}
  }

  let isWritingLog = false;
  function writeToLog(msg) {
    sendToRust(msg);
    logQueue.push(`[${new Date().toISOString()}] ${msg}`);
    if (logQueue.length > 200) {
      logQueue.shift();
    }
    
    if (isWritingLog) return;
    
    // Throttle/Debounce file writes to at most once every 2 seconds
    if (!pendingWriteTimeout) {
      pendingWriteTimeout = setTimeout(async () => {
        pendingWriteTimeout = null;
        isWritingLog = true;
        try {
          await fetch("http://127.0.0.1:8765/api/files/write", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ path: logFile, content: logQueue.join("\n") })
          });
        } catch (_) {}
        finally {
          isWritingLog = false;
        }
      }, 2000);
    }
  }

  const origLog = console.log;
  const origError = console.error;
  const origWarn = console.warn;
  console.log = function(...args) {
    origLog.apply(console, args);
    writeToLog("LOG: " + args.join(" "));
  };
  console.error = function(...args) {
    origError.apply(console, args);
    writeToLog("ERROR: " + args.join(" "));
  };
  console.warn = function(...args) {
    origWarn.apply(console, args);
    writeToLog("WARN: " + args.join(" "));
  };

  window.addEventListener('error', (event) => {
    const msg = (event.message || event.error?.message || '').toString().toLowerCase();
    const isNetworkOrPipe = msg.includes('epipe') ||
                            msg.includes('broken pipe') ||
                            msg.includes('eio') ||
                            msg.includes('econnreset') ||
                            msg.includes('econnrefused') ||
                            msg.includes('network') ||
                            msg.includes('fetch') ||
                            msg.includes('connection closed') ||
                            msg.includes('load failed') ||
                            (event.error && (event.error.code === 'EPIPE' || event.error.errno === -32));
    if (isNetworkOrPipe) {
      event.preventDefault();
      console.warn('[PC Doctor] Suppressed uncaught network/IPC error in listener:', msg);
    }
    writeToLog(`UNCAUGHT ERROR: ${event.message} at ${event.filename}:${event.lineno}:${event.colno}`);
  });

  writeToLog("Webview logging initialized.");
})();


/* ─── Global Error Shield ────────────────────────────────────────────────────
   Catches EIO / EPIPE / ECONNRESET / ECONNREFUSED / network errors that bubble
   up as unhandled promise rejections when the backend is starting, temporarily
   offline, or the IPC channel closes. Without this, Tauri's WebView pops a
   JS error dialog to the user.
──────────────────────────────────────────────────────────────────────────── */
window.addEventListener('unhandledrejection', (event) => {
  const msg = (event.reason?.message || event.reason || '').toString().toLowerCase();
  const isNetworkOrPipe = msg.includes('epipe') ||
                          msg.includes('broken pipe') ||
                          msg.includes('eio') ||
                          msg.includes('econnreset') ||
                          msg.includes('econnrefused') ||
                          msg.includes('network') ||
                          msg.includes('fetch') ||
                          msg.includes('connection closed') ||
                          msg.includes('load failed') ||
                          (event.reason && (event.reason.code === 'EPIPE' || event.reason.errno === -32));
  if (isNetworkOrPipe) {
    event.preventDefault();
    console.warn('[PC Doctor] Backend/IPC error (suppressed):', msg);
    return;
  }
  // All other unhandled rejections: log but don't show native dialog
  event.preventDefault();
  console.error('[PC Doctor] Unhandled rejection:', event.reason);
});

window.onerror = function(message, source, lineno, colno, error) {
  const msg = (message || error?.message || error || '').toString().toLowerCase();
  const isNetworkOrPipe = msg.includes('epipe') ||
                          msg.includes('broken pipe') ||
                          msg.includes('eio') ||
                          msg.includes('econnreset') ||
                          msg.includes('econnrefused') ||
                          msg.includes('network') ||
                          msg.includes('fetch') ||
                          msg.includes('connection closed') ||
                          msg.includes('load failed') ||
                          (error && (error.code === 'EPIPE' || error.errno === -32));
  if (isNetworkOrPipe) {
    console.warn('[PC Doctor] Network/IPC error (suppressed):', msg);
    return true; // suppress
  }
  return false; // let others pass
};

/* ─── Tauri Bridge ──────────────────────────────────────────────────────────
   Provides a unified `window.desktop` interface when running in Tauri.
   To bypass WebKitGTK Mixed Content blocking (fetching local HTTP API on
   an HTTPS page), all loopback fetches are automatically proxied via Rust.
──────────────────────────────────────────────────────────────────────────── */
(function installBridge() {
  const isTauri = !!(window.__TAURI__ || window.__TAURI_INTERNALS__);

  const debugEl = document.getElementById("os-oval-label");
  if (debugEl) {
    const tKeys = window.__TAURI__ ? Object.keys(window.__TAURI__).join(",") : "none";
    const iKeys = window.__TAURI_INTERNALS__ ? Object.keys(window.__TAURI_INTERNALS__).join(",") : "none";
    debugEl.textContent = `T:[${tKeys}] I:[${iKeys}]`;
  }

  if (isTauri) {
    const invoke = window.__TAURI__?.core?.invoke ||
                   window.__TAURI_INTERNALS__?.invoke ||
                   ((...a) => window.__TAURI__.tauri.invoke(...a));

    const listen  = window.__TAURI__?.event?.listen ||
                    window.__TAURI_INTERNALS__?.listen ||
                    ((...a) => window.__TAURI__.event.listen(...a));

    window.desktop = {
      ipcFetch: async (url, opts = {}) => {
        try {
          const method = opts.method || 'GET';
          const headers = {};
          if (opts.headers) {
            const h = new Headers(opts.headers);
            for (const [k, v] of h.entries()) {
              headers[k] = v;
            }
          }
          const body = opts.body || null;
          return await invoke('fetch_api', { url, method, headers, body });
        } catch (err) {
          console.error('[Tauri ipcFetch] error:', err);
          return {
            ok: false,
            status: 503,
            bodyText: err.toString(),
            bodyJson: { ok: false, error: err.toString() }
          };
        }
      },
      startBackend:      () => invoke('start_backend'),
      stopBackend:       () => invoke('stop_backend'),
      getBackendStatus:  () => invoke('get_backend_status'),
      onBackendStatus: (callback) => {
        let unlisten = null;
        listen('backend-status', (event) => callback(event.payload))
          .then(fn => { unlisten = fn; })
          .catch(console.error);
        return () => { if (unlisten) unlisten(); };
      }
    };

    // Intercept global fetch requests to route local API calls through Rust proxy
    const _origFetch = window.fetch;
    window.fetch = async function(url, options) {
      const urlStr = (url || '').toString();
      if (urlStr.startsWith(API) || urlStr.startsWith('/api') || urlStr.includes('/api/')) {
        try {
          const resData = await window.desktop.ipcFetch(urlStr, options);
          return {
            ok: resData.ok,
            status: resData.status,
            statusText: resData.statusText || (resData.ok ? 'OK' : 'Error'),
            headers: new Headers(resData.headers || {}),
            json:  async () => resData.bodyJson,
            text:  async () => resData.bodyText,
            blob:  async () => new Blob([resData.bodyText || ''], { type: 'text/plain' }),
          };
        } catch (err) {
          const errMsg = (err?.message || err?.toString() || '').toLowerCase();
          if (errMsg.includes('epipe') || errMsg.includes('eio') || errMsg.includes('econnreset') ||
              errMsg.includes('broken pipe') || errMsg.includes('connection reset')) {
            console.warn('[PC Doctor] Absorbed IPC pipe error (fetch intercept):', errMsg);
            return {
              ok: false,
              status: 0,
              statusText: 'IPC Error',
              headers: new Headers(),
              json: async () => ({ ok: false }),
              text: async () => '',
              blob: async () => new Blob([], { type: 'text/plain' }),
            };
          }
          console.error('[Tauri Fetch Intercept] error:', err);
          throw err;
        }
      }
      return _origFetch(url, options);
    };

    console.log('[PC Doctor] Running in Tauri mode — Rust IPC fetch proxy enabled.');
  } else {
    console.log('[PC Doctor] Running in browser/dev mode.');
  }
})();

/* ─── State ──────────────────────────────────────────────── */
let pendingCommand    = null;   // { command, risk, title, purpose, affects }
let currentOS         = "Linux";
let pendingAgentCmd   = null;   // { cmd, purpose, risk, resolveCallback }
let isDriverSandbox   = false;
let dashboardRoots    = [];
let currentFolderPath = "";
let parentFolderPath  = null;
let currentFolderWritable = false;
let dashboardMode = "cpu";
let activeViewName = "dashboard";
let gpuUsageInterval = null;
let adaptationCache   = null;
let osLabel           = "Detecting OS…";
let adaptationPct     = 0;
let logEntries        = [];
const SETUP_COMPLETE_KEY = "pc_doctor_setup_complete";
const gpuRingDisplayPct = {};
const activeDriverDownloads = {};

// ── Session-level dismissed scan issues ────────────────────
// Stores issue types the user has clicked "Fix" on this session.
// Prevents the same scan result from reappearing mid-session.
const DISMISSED_SCAN_KEY = "pc_doctor_dismissed_scans";
function getDismissedScans() {
  try { return new Set(JSON.parse(sessionStorage.getItem(DISMISSED_SCAN_KEY) || "[]"));}
  catch { return new Set(); }
}
function dismissScanIssue(issueType) {
  const set = getDismissedScans();
  set.add(issueType);
  sessionStorage.setItem(DISMISSED_SCAN_KEY, JSON.stringify([...set]));
}
function clearDismissedScans() {
  sessionStorage.removeItem(DISMISSED_SCAN_KEY);
}
window.dismissScanIssue = dismissScanIssue;


/* ─── DOM Helpers ────────────────────────────────────────── */
const $ = (id) => document.getElementById(id.startsWith('#') ? id.slice(1) : id);

/* ─── Backend health-check + sysinfo polling ─────────────── */
async function checkBackend(retries = 0) {
  // Don't probe while we're actively shutting down the backend.
  if (backendState === "stopping") return;
  try {
    const r = await fetch(`${API}/api/sysinfo`);
    if (r.ok) {
      const d = await r.json();
      currentOS = d.os;
      osLabel = d.os_label || d.os;
      $("status-dot").className  = "status-dot ok";
      $("status-label").textContent = "Backend online";
      if ($("os-badge")) $("os-badge").textContent = osLabel;
      updateOsOvalBar();
      fetchAdaptationStatus(false);
      // If we were offline/starting/error and now the backend responds,
      // transition to the correct online state and load dashboard data.
      if (backendState !== "online" && backendState !== "external") {
        updateBackendUI("external");
        loadDashboardDetails();
      } else {
        // Self-healing: if the backend is online/external but the app list
        // is still in a loading or error state, trigger dashboard reload.
        const appList = $("linux-app-list");
        if (appList && (appList.innerHTML.includes("Loading") || appList.innerHTML.includes("Unable") || appList.innerHTML.includes("Waiting"))) {
          loadDashboardDetails();
        }
      }
      updateStats(d);
    } else throw new Error();
  } catch {
    if (retries < 6 && $("status-label").textContent.includes("online")) {
      setTimeout(() => checkBackend(retries + 1), 500);
      return;
    }
    // Only mark offline if we're not in the 'starting' window (Tauri is
    // still spawning the process); in that state the Rust side will emit
    // the definitive status via the backend-status event.
    if (backendState !== "starting") {
      $("status-dot").className  = "status-dot err";
      $("status-label").textContent = "Backend offline";
      if ($("os-badge")) $("os-badge").textContent  = "–";
      if (backendState !== "offline") updateBackendUI("offline");
    }
  }
}

function updateStats(d) {
  const cpuPct  = d.cpu_percent;
  const ramPct  = d.ram_total_gb  > 0 ? (d.ram_used_gb  / d.ram_total_gb  * 100) : 0;
  const diskPct = d.disk_total_gb > 0 ? (d.disk_used_gb / d.disk_total_gb * 100) : 0;

  if ($("ram-val")) $("ram-val").textContent  = `${d.ram_used_gb} / ${d.ram_total_gb} GB`;
  if ($("disk-val")) $("disk-val").textContent = `${d.disk_used_gb} / ${d.disk_total_gb} GB`;

  animateBar("cpu-bar",  cpuPct);
  animateBar("ram-bar",  ramPct);
  animateBar("disk-bar", diskPct);
  const cpuCoresText = d.cpu_cores ? `${d.cpu_cores} Cores` : "Utilization";
  updateResourceTile("cpu-ring-val", "cpu-ring-detail", cpuPct, cpuCoresText);
  updateResourceTile("ram-ring-val", "ram-ring-detail", ramPct, `${d.ram_used_gb} / ${d.ram_total_gb} GB`);
  updateResourceTile("disk-ring-val", "disk-ring-detail", diskPct, `${d.disk_used_gb} / ${d.disk_total_gb} GB`);
}

function animateBar(id, pct) {
  const el = $(id);
  if (!el) return;
  el.style.width = Math.min(pct, 100) + "%";
  el.style.background =
    pct > 85 ? "var(--risk-high)" :
    pct > 60 ? "var(--risk-med)"  : "var(--grad)";
}

function updateUsageRing(ringId, labelId, pct) {
  const ring = $(ringId);
  const label = $(labelId);
  const target = Math.max(0, Math.min(Number(pct) || 0, 100));
  if (!ring) return;

  const start = Number(gpuRingDisplayPct[ringId] ?? ring.style.getPropertyValue("--pct") ?? 0);
  if (Math.abs(start - target) < 0.5) {
    ring.style.setProperty("--pct", target.toFixed(1));
    let color = "var(--apple-mint)";
    if (ring.classList.contains("dedicated")) {
      color = "var(--apple-cyan)";
    } else if (ring.classList.contains("disk")) {
      color = "var(--apple-blue)";
    } else if (ring.classList.contains("integrated")) {
      color = "var(--apple-cyan)";
    }
    if (target > 85) {
      color = "var(--risk-high)";
    } else if (target > 60) {
      color = "var(--risk-med)";
    }
    ring.style.setProperty("--ring-color", color);
    gpuRingDisplayPct[ringId] = target;
    if (label) label.textContent = `${Math.round(target)}%`;
    return;
  }

  const duration = 650;
  const started = performance.now();
  function frame(now) {
    const t = Math.min(1, (now - started) / duration);
    const eased = t * (2 - t);
    const current = start + (target - start) * eased;
    ring.style.setProperty("--pct", current.toFixed(1));
    let color = "var(--apple-mint)";
    if (ring.classList.contains("dedicated")) {
      color = "var(--apple-cyan)";
    } else if (ring.classList.contains("disk")) {
      color = "var(--apple-blue)";
    } else if (ring.classList.contains("integrated")) {
      color = "var(--apple-cyan)";
    }
    if (current > 85) {
      color = "var(--risk-high)";
    } else if (current > 60) {
      color = "var(--risk-med)";
    }
    ring.style.setProperty("--ring-color", color);
    gpuRingDisplayPct[ringId] = current;
    if (label) label.textContent = `${Math.round(current)}%`;
    if (t < 1) requestAnimationFrame(frame);
  }
  requestAnimationFrame(frame);
}

function isSetupComplete() {
  return localStorage.getItem(SETUP_COMPLETE_KEY) === "true";
}

function markSetupComplete() {
  localStorage.setItem(SETUP_COMPLETE_KEY, "true");
  updateOsOvalBar();
}

function maybeCompleteSetupFromProgress() {
  if (!isSetupComplete() && Number(adaptationPct || 0) >= 80) {
    markSetupComplete();
  }
}

function updateResourceTile(valueId, detailId, pct, detail) {
  const value = $(valueId);
  const detailEl = $(detailId);
  const clamped = Math.max(0, Math.min(Number(pct) || 0, 100));
  if (value) value.textContent = `${clamped.toFixed(0)}%`;
  if (detailEl) detailEl.textContent = detail;
}

async function fetchGpuUsage() {
  try {
    const r = await fetch(`${API}/api/gpu_usage`);
    if (!r.ok) throw new Error("GPU usage request failed");
    const d = await r.json();
    return d;
  } catch (err) {
    return { ok: false, available: false, message: "Unable to retrieve GPU utilization." };
  }
}

function normalizeGpuUsagePayload(data) {
  if (!data || !data.ok) return [];
  if (Array.isArray(data.gpus) && data.gpus.length) return data.gpus;
  if (data.available) {
    return [{
      name: data.name || "GPU",
      kind: data.type === "nvidia" ? "dedicated" : "integrated",
      kind_label: data.type === "nvidia" ? "Dedicated GPU" : "Integrated GPU",
      available: true,
      usage_pct: data.usage_pct,
      mem_used_mb: data.mem_used_mb,
      mem_total_mb: data.mem_total_mb,
      temperature_c: data.temperature_c,
      source: data.type === "nvidia" ? "nvidia-smi" : "system",
    }];
  }
  return [];
}

function renderGpuUsageDetails(gpu, index) {
  const lines = [];
  if (gpu.kind === "integrated" && gpu.integrated_status) {
    lines.push(`Integrated GPU Status: ${escHtml(gpu.integrated_status)}`);
  }
  if (gpu.mem_used_mb !== undefined && gpu.mem_total_mb !== undefined) {
    lines.push(`Memory: ${escHtml(String(gpu.mem_used_mb))} / ${escHtml(String(gpu.mem_total_mb))} MB`);
  }
  if (gpu.temperature_c !== undefined) {
    lines.push(`Temperature: ${escHtml(String(gpu.temperature_c))}°C`);
  }
  if (gpu.source && gpu.source !== "unavailable") {
    lines.push(`Source: ${escHtml(gpu.source)}`);
  }
  if (gpu.message) {
    lines.push(escHtml(gpu.message));
  }
  return lines.map(line => `<div class="driver-detail gpu-usage-detail" data-gpu-detail="${index}" style="color:var(--text-2)">${line}</div>`).join("");
}

function updateGpuUsageCard(data) {
  const card = $("gpu-usage-card");
  if (!card) return;

  let gpus = normalizeGpuUsagePayload(data);
  
  // Filter out dedicated GPUs that are not active/available (dissolve them)
  gpus = gpus.filter(gpu => {
    if (gpu.kind === "dedicated") {
      return gpu.available; // only show dedicated if active/available
    }
    return true; // always show integrated (even if available is false/inactive)
  });

  if (!gpus.length) {
    card.dataset.gpuCount = "0";
    card.className = "driver-card";
    card.innerHTML = `
      <div class="driver-title">GPU Consumption</div>
      <div class="driver-detail" style="color:var(--text-2)">${escHtml(data?.message || "GPU utilization data unavailable.")}</div>
    `;
    return;
  }

  const signature = gpus.map(gpu => `${gpu.kind}:${gpu.name}:${gpu.available}`).join("|");
  if (card.dataset.gpuSignature === signature && card.querySelector(".gpu-usage-grid")) {
    gpus.forEach((gpu, index) => {
      const pct = Math.max(0, Math.min(Number(gpu.usage_pct) || 0, 100));
      const label = gpu.available ? `${pct}%` : "N/A";
      updateUsageRing(`gpu-usage-ring-${index}`, `gpu-usage-label-${index}`, pct);
      const labelEl = $(`gpu-usage-label-${index}`);
      if (labelEl) labelEl.textContent = label;
      const meta = card.querySelector(`[data-gpu-meta="${index}"]`);
      if (meta) meta.innerHTML = renderGpuUsageDetails(gpu, index);
    });
    return;
  }

  card.dataset.gpuSignature = signature;
  card.dataset.gpuCount = String(gpus.length);
  card.className = "driver-card";
  const gridClass = gpus.length === 1 ? "gpu-usage-grid single-gpu" : "gpu-usage-grid";
  card.innerHTML = `
    <div class="driver-title">GPU Consumption</div>
    <div class="driver-detail" style="color:var(--text-2);margin-bottom:.9rem">Integrated and dedicated GPU usage levels refresh every second.</div>
    <div class="${gridClass}">
      ${gpus.map((gpu, index) => {
        const pct = Math.max(0, Math.min(Number(gpu.usage_pct) || 0, 100));
        const ringClass = gpu.kind === "integrated" ? "usage-ring integrated" : "usage-ring dedicated";
        const label = gpu.available ? `${pct}%` : "N/A";
        return `
          <div class="gpu-usage-item">
            <div class="${ringClass}" id="gpu-usage-ring-${index}">
              <div>
                <strong id="gpu-usage-label-${index}">${label}</strong>
                <span>${escHtml(gpu.kind_label || (gpu.kind === "integrated" ? "Integrated GPU" : "Dedicated GPU"))}</span>
              </div>
            </div>
            <div class="driver-detail" style="margin-top:.55rem;font-weight:600">${escHtml(gpu.name || "GPU")}</div>
            <div class="gpu-usage-meta" data-gpu-meta="${index}">
              ${renderGpuUsageDetails(gpu, index)}
            </div>
          </div>
        `;
      }).join("")}
    </div>
  `;
  gpus.forEach((gpu, index) => {
    if (gpu.available) {
      updateUsageRing(`gpu-usage-ring-${index}`, `gpu-usage-label-${index}`, gpu.usage_pct || 0);
    }
  });
}

async function refreshGpuUsage(showLoading = false) {
  const card = $("gpu-usage-card");
  if (showLoading && card && !card.querySelector(".gpu-usage-grid")) {
    card.className = "driver-card";
    card.innerHTML = `
      <div class="driver-title">GPU Consumption</div>
      <div class="driver-detail" style="color:var(--text-2)">Loading GPU utilization…</div>
    `;
  }
  const data = await fetchGpuUsage();
  updateGpuUsageCard(data);
}

function startGpuUsageRefresh() {
  stopGpuUsageRefresh();
  refreshGpuUsage(true);
  gpuUsageInterval = setInterval(() => {
    if (activeViewName !== "drivers") {
      stopGpuUsageRefresh();
      return;
    }
    refreshGpuUsage(false);
  }, 1000);
}

function stopGpuUsageRefresh() {
  if (gpuUsageInterval) {
    clearInterval(gpuUsageInterval);
    gpuUsageInterval = null;
  }
}

function showDashboardMode(mode) {
  dashboardMode = mode;
  $("dashboard-cpu-tile")?.classList.toggle("active", mode === "cpu");
  $("dashboard-ram-tile")?.classList.toggle("active", mode === "ram");
  $("dashboard-storage-tile")?.classList.toggle("active", mode === "storage");
  $("dashboard-health-tile")?.classList.toggle("active", mode === "self-healing");
  $("dashboard-adaptation-tile")?.classList.toggle("active", mode === "self-healing");

  $("dashboard-cpu-panel")?.classList.toggle("active", mode === "cpu");
  $("dashboard-ram-panel")?.classList.toggle("active", mode === "ram");
  $("dashboard-storage-panel")?.classList.toggle("active", mode === "storage");
  $("dashboard-self-healing-panel")?.classList.toggle("active", mode === "self-healing");

  if (mode === "storage" && dashboardRoots.length && !currentFolderPath) {
    loadFolder(dashboardRoots[0].path);
  }
  if (mode === "self-healing") {
    refreshSelfHealingDashboard();
  }
}

async function loadDashboardDetails() {
  // If the backend is still starting, show a friendly waiting message and
  // return early – the onBackendStatus listener will call us again once online.
  if (backendState === 'starting' || backendState === 'offline' || backendState === 'error') {
    const appList = $("linux-app-list");
    const cpuAppList = $("linux-cpu-app-list");
    const fileList = $("file-list");
    if (appList) appList.innerHTML = `<div class="empty-row">⏳ Waiting for backend to start…</div>`;
    if (cpuAppList) cpuAppList.innerHTML = `<div class="empty-row">⏳ Waiting for backend to start…</div>`;
    if (fileList && fileList.textContent === 'Loading folders...') {
      fileList.textContent = '⏳ Waiting for backend…';
    }
    return;
  }

  const appList = $("linux-app-list");
  const cpuAppList = $("linux-cpu-app-list");
  if (appList) appList.innerHTML = `<div class="empty-row">Loading applications...</div>`;
  if (cpuAppList) cpuAppList.innerHTML = `<div class="empty-row">Loading applications...</div>`;

  try {
    const r = await fetch(`${API}/api/dashboard/resources`);
    if (!r.ok) throw new Error(`HTTP ${r.status}`);
    const d = await r.json();
    if (!d.ok) throw new Error("Bad dashboard response");
    dashboardRoots = d.roots || [];
    renderLinuxApps(d.apps || []);
    renderLinuxCpuApps(d.apps || []);
    renderFolderTabs();
    // Always load the folder view – default to Home if no folder is selected yet
    loadFolder(currentFolderPath || (dashboardRoots[0] && dashboardRoots[0].path));
  } catch (err) {
    console.error('[Dashboard] resources fetch failed:', err);
    if ($("file-list")) $("file-list").textContent = "Unable to load folders. Is the backend running?";
    if (appList) appList.innerHTML = `<div class="empty-row">Unable to load app list. Is the backend running?</div>`;
    if (cpuAppList) cpuAppList.innerHTML = `<div class="empty-row">Unable to load app list. Is the backend running?</div>`;
  }

  // Load System Health and Adaptation Score tiles
  try {
    const shRes = await fetch(`${API}/api/self-healing/status`);
    if (!shRes.ok) throw new Error(`HTTP ${shRes.status}`);
    const shData = await shRes.json();
    if (shData.ok) {
      const healthPct = shData.system_health;
      const adaptationScore = shData.adaptation_score || 0;
      
      const healthValEl = $("health-ring-val");
      const healthDetailEl = $("health-ring-detail");
      if (healthValEl) {
        healthValEl.textContent = healthPct === "Unknown" ? "Unknown" : `${healthPct}%`;
      }
      if (healthDetailEl) {
        if (healthPct === "Unknown") {
          healthDetailEl.textContent = "Run Scan";
          healthDetailEl.style.color = "var(--text-3)";
        } else {
          healthDetailEl.textContent = healthPct >= 90 ? "Excellent" : healthPct >= 70 ? "Warning" : "Critical Issues";
          healthDetailEl.style.color = healthPct >= 90 ? "#79f2c0" : healthPct >= 70 ? "#fde047" : "#ef4444";
        }
      }

      const adaptValEl = $("adaptation-ring-val");
      const adaptDetailEl = $("adaptation-ring-detail");
      if (adaptValEl) adaptValEl.textContent = `${adaptationScore}%`;
      if (adaptDetailEl) {
        adaptDetailEl.textContent = "OS Coherence";
      }
    }
  } catch (shErr) {
    console.error("Failed to load self-healing status on dashboard:", shErr);
  }
}

function renderFolderTabs() {
  const tabs = $("folder-tabs");
  if (!tabs) return;
  tabs.innerHTML = dashboardRoots.map(root => `
    <button class="folder-tab ${currentFolderPath === root.path ? "active" : ""}" onclick="loadFolder(${escHtml(JSON.stringify(root.path))})">
      <svg><use href="${root.path === "/" ? "#icon-monitor" : "#icon-folder"}"></use></svg>
      <span>${escHtml(root.label)}</span>
    </button>
  `).join("");
}

async function loadFolder(path) {
  if (!path) return;
  const list = $("file-list");
  if (list) list.innerHTML = `<div class="empty-row">Loading folder...</div>`;
  try {
    const r = await fetch(`${API}/api/files/list?path=${encodeURIComponent(path)}`);
    const d = await r.json();
    if (!d.ok) throw new Error(d.detail || "Folder load failed");
    currentFolderPath = d.path;
    parentFolderPath = d.parent;
    currentFolderWritable = d.writable === true;
    renderFolderTabs();
    renderFileList(d);
  } catch (err) {
    if (list) list.innerHTML = `<div class="empty-row">Cannot open folder: ${escHtml(err.message)}</div>`;
  }
}

function goFolderUp() {
  if (parentFolderPath) loadFolder(parentFolderPath);
}

function formatFileSize(bytes, sizeGb) {
  if (bytes === undefined || bytes === null || bytes === 0) {
    if (sizeGb && sizeGb > 0) {
      bytes = sizeGb * 1024 * 1024 * 1024;
    } else {
      return "0 Bytes";
    }
  }
  if (bytes < 1024) return bytes + " Bytes";
  const kb = bytes / 1024;
  if (kb < 1024) return kb.toFixed(2) + " KB";
  const mb = kb / 1024;
  if (mb < 1024) return mb.toFixed(2) + " MB";
  const gb = mb / 1024;
  return gb.toFixed(2) + " GB";
}

function renderFileList(data) {
  const list = $("file-list");
  const pathEl = $("folder-current-path");
  const upBtn = $("folder-up-btn");
  const writeState = $("file-write-state");
  if (pathEl) pathEl.textContent = data.path;
  if (upBtn) upBtn.disabled = !data.parent;
  if (writeState) {
    if (data.is_os_path) {
      writeState.textContent = "OS Files (Readable & Protected)";
      writeState.className = "write-state protected";
    } else {
      writeState.textContent = data.writable ? "Writable" : "Protected";
      writeState.className = data.writable ? "write-state writable" : "write-state protected";
    }
  }
  document.querySelectorAll("#file-actions button").forEach(btn => {
    btn.disabled = !data.writable;
  });
  if (!list) return;
  if (!data.entries.length) {
    list.innerHTML = `<div class="empty-row">Folder is empty or unreadable. Read-only mode is active.</div>`;
    return;
  }
  list.innerHTML = data.entries.map(entry => {
    const isOSProtected = !entry.writable && (data.is_os_path || !entry.path.startsWith("/home"));
    return `
    <div class="file-row ${entry.type === "folder" ? "folder" : "file"}">
      <svg><use href="${entry.type === "folder" ? "#icon-folder" : "#icon-file"}"></use></svg>
      <span class="file-name">${escHtml(entry.name)}</span>
      <span class="file-meta">${entry.type === "folder" ? "Folder" : formatFileSize(entry.size_bytes, entry.size_gb)}</span>
      <span class="read-only-badge ${entry.writable ? 'writable' : 'protected'}">
        ${entry.writable ? "Writable" : (data.is_os_path || !entry.path.startsWith("/home") ? "OS Protected" : "Protected")}
      </span>
      <span class="file-row-actions">
        ${entry.type === "folder" && !isOSProtected ? `<button class="quiet-btn" onclick="loadFolder(${escHtml(JSON.stringify(entry.path))})">Open</button>` : ""}
        ${entry.editable ? `<button class="quiet-btn" onclick="editFile(${escHtml(JSON.stringify(entry.path))})">Edit</button>` : ""}
        ${entry.writable ? `<button class="quiet-btn danger-btn" style="color:var(--risk-high);border-color:rgba(239,68,68,0.25);" onclick="deleteFile(${escHtml(JSON.stringify(entry.path))})">Delete</button>` : ""}
      </span>
    </div>`;
  }).join("");
}

async function createCurrentFolder() {
  if (!currentFolderWritable) return;
  const name = prompt("Folder name");
  if (!name) return;
  await createPath("create_folder", name);
}

async function createCurrentFile() {
  if (!currentFolderWritable) return;
  const name = prompt("File name");
  if (!name) return;
  await createPath("create_file", name);
}

async function createPath(endpoint, name) {
  try {
    const r = await fetch(`${API}/api/files/${endpoint}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ path: currentFolderPath, name }),
    });
    const d = await r.json();
    if (!r.ok || !d.ok) throw new Error(d.detail || "Create failed");
    showToast(`${endpoint === "create_folder" ? "Folder" : "File"} created.`, "ok");
    loadFolder(currentFolderPath);
  } catch (err) {
    showToast(`Could not create: ${err.message}`, "err");
  }
}

async function editFile(path) {
  try {
    const r = await fetch(`${API}/api/files/read?path=${encodeURIComponent(path)}`);
    const d = await r.json();
    if (!r.ok || !d.ok) throw new Error(d.detail || "Read failed");
    const next = prompt(`Edit ${path}`, d.content);
    if (next === null) return;
    const wr = await fetch(`${API}/api/files/write`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ path, content: next }),
    });
    const saved = await wr.json();
    if (!wr.ok || !saved.ok) throw new Error(saved.detail || "Save failed");
    showToast("File saved.", "ok");
    loadFolder(currentFolderPath);
  } catch (err) {
    showToast(`Could not edit file: ${err.message}`, "err");
  }
}

async function deleteFile(path) {
  const fileName = path.split('/').pop() || "item";
  if (!confirm(`Are you sure you want to permanently delete this ${fileName}?\n\nPath: ${path}`)) return;
  try {
    const r = await fetch(`${API}/api/files/delete`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ path }),
    });
    const d = await r.json();
    if (!r.ok || !d.ok) throw new Error(d.detail || "Delete failed");
    showToast("✓ File deleted.", "ok");
    loadFolder(currentFolderPath);
  } catch (err) {
    showToast(`Could not delete: ${err.message}`, "err");
  }
}


function renderLinuxApps(apps) {
  const el = $("linux-app-list");
  if (!el) return;
  if (!apps.length) {
    el.innerHTML = `<div class="empty-row">No non-critical user apps are currently taking notable resources.</div>`;
    return;
  }
  el.innerHTML = apps.map(app => `
    <div class="app-row ${app.stoppable === false ? "necessary" : ""}">
      <div>
        <div class="app-name">${escHtml(app.name)} <span style="color:var(--text-3);font-weight:500">${Number(app.process_count || 1)} process${Number(app.process_count || 1) === 1 ? "" : "es"}</span></div>
        <div class="app-command">${escHtml(app.command || "User process")}</div>
      </div>
      <div class="app-metrics">${escHtml(app.category || "Application")} · CPU ${Number(app.cpu_percent || 0).toFixed(1)}% · RAM ${Number(app.memory_percent || 0).toFixed(1)}%</div>
      ${app.stoppable === false
        ? `<button class="stop-btn disabled" disabled title="Necessary Linux app. Stop is disabled for system safety.">Protected</button>`
        : app.browser_control
          ? `<button class="stop-btn browser" onclick="closeOtherBrowserTabs(${escHtml(JSON.stringify(app.pids || [app.pid]))}, ${escHtml(JSON.stringify(app.name || "Browser"))})">Close Other Tabs</button>`
          : `<button class="stop-btn" onclick="stopLinuxApp(${escHtml(JSON.stringify(app.pids || [app.pid]))}, ${escHtml(JSON.stringify(app.name || "App"))})">Stop</button>`
      }
    </div>
  `).join("");
}

function renderLinuxCpuApps(apps) {
  const el = $("linux-cpu-app-list");
  if (!el) return;
  if (!apps.length) {
    el.innerHTML = `<div class="empty-row">No apps are currently taking notable CPU resources.</div>`;
    return;
  }
  
  // Sort by CPU percent descending for normal apps, keep necessary (stoppable === false) at the bottom
  const normalApps = apps.filter(app => app.stoppable !== false);
  const necessaryApps = apps.filter(app => app.stoppable === false);
  
  // Sort both by CPU percent descending
  normalApps.sort((a, b) => b.cpu_percent - a.cpu_percent);
  necessaryApps.sort((a, b) => b.cpu_percent - a.cpu_percent);
  
  const sortedApps = [...normalApps, ...necessaryApps];
  
  el.innerHTML = sortedApps.map(app => `
    <div class="app-row ${app.stoppable === false ? "necessary" : ""}">
      <div>
        <div class="app-name">${escHtml(app.name)} <span style="color:var(--text-3);font-weight:500">${Number(app.process_count || 1)} process${Number(app.process_count || 1) === 1 ? "" : "es"}</span></div>
        <div class="app-command">${escHtml(app.command || "User process")}</div>
      </div>
      <div class="app-metrics">${escHtml(app.category || "Application")} · CPU ${Number(app.cpu_percent || 0).toFixed(1)}% · RAM ${Number(app.memory_percent || 0).toFixed(1)}%</div>
      ${app.stoppable === false
        ? `<button class="stop-btn disabled" disabled title="Necessary Linux app. Stop is disabled for system safety.">Protected</button>`
        : app.browser_control
          ? `<button class="stop-btn browser" onclick="closeOtherBrowserTabs(${escHtml(JSON.stringify(app.pids || [app.pid]))}, ${escHtml(JSON.stringify(app.name || "Browser"))})">Close Other Tabs</button>`
          : `<button class="stop-btn" onclick="stopLinuxApp(${escHtml(JSON.stringify(app.pids || [app.pid]))}, ${escHtml(JSON.stringify(app.name || "App"))})">Stop</button>`
      }
    </div>
  `).join("");
}

async function closeOtherBrowserTabs(pids, name) {
  // First request a preview so the user can confirm which renderer PIDs would
  // be affected. This avoids accidentally closing the PC Doctor tab.
  try {
    const previewRes = await fetch(`${API}/api/browser/close_other_tabs`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ pids, name, preview: true }),
    });
    const preview = await previewRes.json();
    if (!previewRes.ok || !preview.ok) throw new Error(preview.detail || "Preview failed");

    const count = (preview.targets || preview.candidates || []).length;
    if (count === 0) {
      showToast(preview.message || `No other ${name} tab processes detected.`, "err");
      return;
    }

    const list = (preview.targets && preview.targets.length) ? preview.targets : preview.candidates;
    const summary = list.map(x => `${x.pid} ${x.cmd ? '- ' + x.cmd.slice(0,80) : ''}`).join('\n');
    if (!confirm(`Preview: ${count} renderer process(es) will be closed for ${name}:\n\n${summary}\n\nProceed?`)) return;

    // User confirmed — perform actual close
    const r = await fetch(`${API}/api/browser/close_other_tabs`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ pids, name }),
    });
    const d = await r.json();
    if (!r.ok || !d.ok) throw new Error(d.detail || "Close tabs failed");
    showToast(d.message || "Closed other browser tabs.", "ok");
    loadDashboardDetails();
  } catch (err) {
    showToast(`Could not close browser tabs: ${err.message}`, "err");
  }
}

async function stopLinuxApp(pids, name) {
  const lower = String(name).toLowerCase();
  const browserWarning = ["brave", "chrome", "chromium", "firefox"].some(browser => lower.includes(browser))
    ? "\n\nThis looks like your browser. If PC Doctor is open in it, the page will close before it can show the result."
    : "";
  if (!confirm(`Stop ${name}? Unsaved work in that app may be lost.${browserWarning}`)) return;
  try {
    const r = await fetch(`${API}/api/process/stop`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ pid: pids[0] || 0, pids }),
    });
    const d = await r.json();
    if (!r.ok || !d.ok) throw new Error(d.detail || "Stop failed");
    showToast(d.message || `Stopped ${name}`, "ok");
    loadDashboardDetails();
  } catch (err) {
    showToast(`Could not stop ${name}: ${err.message}`, "err");
  }
}

async function boostRam() {
  const actions = await getCommandActions();
  const boostAction = actions.boost_ram || {
    command: "sync && echo 3 | sudo tee /proc/sys/vm/drop_caches",
    risk: "Medium",
    explanation: "Flushes kernel caches and stops background applications."
  };
  if (!confirm("Boost RAM? PC Doctor will show and run the memory optimization operation that matches your OS.")) {
    return;
  }
  showToast("Boosting RAM. Please wait...", "ok");
  try {
    const r = await fetch(`${API}/api/execute`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        command: boostAction.command,
        risk: boostAction.risk || "Medium",
        title: "Boost RAM",
        purpose: boostAction.explanation || "Optimizes memory for the current OS."
      })
    });
    const d = await r.json();
    if (!r.ok) {
      throw new Error(d.detail || "RAM Boost failed");
    }
    
    let msg = "RAM Boost completed successfully!";
    if (d.closed_apps && d.closed_apps.length > 0) {
      msg += ` Closed apps: ${d.closed_apps.join(", ")}`;
    }
    showToast(msg, "ok");
    loadDashboardDetails();
  } catch (err) {
    showToast(`Could not boost RAM: ${err.message}`, "err");
  }
}


/* ─── View switching ─────────────────────────────────────── */
function switchView(name, forceImmediate = false) {
  if (window.PCDoctorAnimations && window.PCDoctorAnimations.isEnabled() && !forceImmediate) {
    window.PCDoctorAnimations.animateViewTransition(name, () => {
      switchView(name, true);
    });
    return;
  }
  if (activeViewName === "drivers" && name !== "drivers") {
    stopGpuUsageRefresh();
  }
  activeViewName = name;
  document.querySelectorAll(".view").forEach(v => v.classList.remove("active"));
  document.querySelectorAll(".nav-item").forEach(n => n.classList.remove("active"));

  const view = $(`view-${name}`);
  const nav  = $(`nav-${name}`);
  if (view) view.classList.add("active");
  if (nav)  nav.classList.add("active");

  const titles = {
    dashboard: "Dashboard", scan: "Scan PC", repair: "Repair Problems",
    optimize: "Optimize System", devtools: "Dev Tools",
    drivers: "Driver Manager", "terminal-ai": "AI Terminal Agent",
    logs: "Action Logs", "os-adaptation": "Control Center",
  };
  $("view-title").textContent = titles[name] || "PC Doctor";

  // Force a fresh recipe fetch if we only have fallback data (backend wasn't ready on init)
  if (name === "repair")      loadRecipes(allRecipes.isFallback ? true : false);
  if (name === "scan")        runSequentialScan();
  if (name === "dashboard") {
    loadDashboardDetails();
    refreshDashboardIfOnline();
  }
  if (name === "optimize")    loadOptimizeCards(false);
  if (name === "devtools")    loadDevToolCards(false);
  if (name === "os-adaptation") loadOsAdaptationTab(false);
  if (name === "logs")        loadLogs();
  if (name === "drivers") {
    loadDrivers();
    startGpuUsageRefresh();
  }
  if (name === "terminal-ai") {
    checkOllamaServiceStatus();
    if (!ollamaStatusInterval) {
      ollamaStatusInterval = setInterval(checkOllamaServiceStatus, 4000);
    }
  } else {
    if (ollamaStatusInterval) {
      clearInterval(ollamaStatusInterval);
      ollamaStatusInterval = null;
    }
  }
}

document.querySelectorAll(".nav-item").forEach(btn => {
  btn.addEventListener("click", () => switchView(btn.dataset.view));
});

// Backend toggle button handling
let backendState = "offline";

function updateBackendUI(status) {
  backendState = status;
  const btn = $('#backend-toggle-btn');
  const dot = $('#status-dot');
  const label = $('#status-label');
  const drawerLabel = $('drawer-backend-status-label');
  const drawerBtn = $('drawer-backend-toggle-btn');

  if (!btn || !dot || !label) return;

  btn.disabled = status === 'starting' || status === 'stopping';
  if (drawerBtn) drawerBtn.disabled = btn.disabled;

  if (status === 'online' || status === 'external') {
    dot.className = 'status-dot ok';
    label.textContent = status === 'external' ? 'Backend online (external)' : 'Backend online';
    btn.textContent = status === 'external' ? 'Backend Running' : 'Stop Backend';
    if (drawerLabel) drawerLabel.textContent = status === 'external' ? 'Backend is already running outside the app' : 'Backend is online';
    if (drawerBtn) drawerBtn.textContent = status === 'external' ? 'Running' : 'Stop';
    return;
  }

  if (status === 'starting' || status === 'stopping') {
    dot.className = 'status-dot';
    label.textContent = status === 'starting' ? 'Backend starting...' : 'Backend stopping...';
    btn.textContent = status === 'starting' ? 'Starting...' : 'Stopping...';
    if (drawerLabel) drawerLabel.textContent = status === 'starting' ? 'Backend is starting' : 'Backend is stopping';
    if (drawerBtn) drawerBtn.textContent = status === 'starting' ? 'Starting...' : 'Stopping...';
    return;
  }

  if (status === 'error') {
    dot.className = 'status-dot err';
    label.textContent = 'Backend failed to start';
    btn.textContent = 'Start Backend';
    if (drawerLabel) drawerLabel.textContent = 'Backend failed to start';
    if (drawerBtn) drawerBtn.textContent = 'Start';
    return;
  }

    dot.className = 'status-dot err';
    label.textContent = 'Backend offline';
    btn.textContent = 'Start Backend';
    if (drawerLabel) drawerLabel.textContent = 'Backend is offline';
    if (drawerBtn) drawerBtn.textContent = 'Start';
}

// Listen for backend status events from the Rust host
if (window.desktop?.onBackendStatus) {
  window.desktop.onBackendStatus(async (status) => {
    updateBackendUI(status);
    if (status === 'online' || status === 'external') {
      // Backend just came online – refresh the dashboard unconditionally so
      // the user sees real data even if they haven't switched views yet.
      await checkBackend();
      await loadDashboardDetails();
      if (activeViewName !== 'dashboard') {
        // Also run the active view's refresh so e.g. Repair page gets recipes
        refreshActiveView();
      }
    }
  });
}

// Click handler for toggle buttons
async function toggleBackend() {
  if (!window.desktop?.startBackend) {
    showToast("Backend control is available in the desktop app. In browser mode, start backend manually.", "err");
    return;
  }

  try {
    if (backendState === 'online') {
      updateBackendUI('stopping');
      const status = await window.desktop.stopBackend();
      updateBackendUI(status);
    } else if (backendState === 'external') {
      showToast("Backend was started outside this app, so PC Doctor cannot stop that process.", "err");
      updateBackendUI('external');
      await refreshDashboardIfOnline();
    } else {
      updateBackendUI('starting');
      const status = await window.desktop.startBackend();
      updateBackendUI(status);
      if (status === 'online' || status === 'external') await refreshDashboardIfOnline();
      if (status === 'error') showToast("Backend did not become ready. Check the terminal output.", "err");
    }
  } catch (err) {
    updateBackendUI('error');
    showToast(`Backend control failed: ${err.message}`, "err");
  }
}


async function refreshDashboardIfOnline() {
  if (backendState === 'online' || backendState === 'external') {
    await checkBackend();
    if (activeViewName === 'dashboard') {
      await loadDashboardDetails();
    }
  }
}

$('#backend-toggle-btn')?.addEventListener('click', toggleBackend);
document.getElementById('drawer-backend-toggle-btn')?.addEventListener('click', toggleBackend);

/* ─── SCAN ───────────────────────────────────────────────── */
async function runSequentialScan() {
  const btn = $("btn-scan");
  if (!btn) return;
  btn.disabled = true;
  btn.innerHTML = '<span class="spinner"></span> Scanning…';
  $("scan-results").innerHTML = "";

  const core = $("scan-scope-core").checked;
  const dev  = $("scan-scope-dev").checked;

  if (!core && !dev) {
    $("scan-results").innerHTML =
      `<div class="issue-card"><span>⚠️</span><div class="issue-body">
        <div class="issue-title">No Scan Scope Selected</div>
        <div class="issue-detail">Please select at least one scan category above.</div>
      </div></div>`;
    btn.disabled = false;
    btn.textContent = "Start Scan";
    return;
  }

  const progressContainer = $("scan-progress-container");
  if (progressContainer) progressContainer.classList.remove("hidden");
  
  const progressStatus = $("scan-progress-status");
  const progressPct = $("scan-progress-pct");
  const progressFill = $("scan-progress-fill");
  const stepsList = $("scan-steps-list");

  if (progressStatus) progressStatus.textContent = "Initializing scan...";
  if (progressPct) progressPct.textContent = "0%";
  if (progressFill) progressFill.style.width = "0%";

  try {
    const r = await fetch(`${API}/api/scan/steps`);
    const d = await r.json();
    const allSteps = d.steps || [];

    const activeSteps = allSteps.filter(step => {
      if (step.id === "dev_tools") return dev;
      return core;
    });

    if (stepsList) {
      stepsList.innerHTML = activeSteps.map(step => `
        <div class="scan-step-item" id="scan-step-${step.id}">
          <span class="step-icon" id="scan-step-icon-${step.id}">⏳</span>
          <span class="step-title">${escHtml(step.title)}</span>
        </div>
      `).join("");
    }

    let accumulatedIssues = [];
    let completedCount = 0;

    for (const step of activeSteps) {
      const itemEl = $(`scan-step-${step.id}`);
      const iconEl = $(`scan-step-icon-${step.id}`);
      if (itemEl) itemEl.classList.add("active");
      if (iconEl) iconEl.innerHTML = '<span class="spinner" style="width: 12px; height: 12px; border-width: 2px; display: inline-block;"></span>';
      if (progressStatus) progressStatus.textContent = `Scanning: ${step.title}...`;

      try {
        const stepRes = await fetch(`${API}/api/scan/run?step=${step.id}`);
        const stepData = await stepRes.json();
        const stepIssues = stepData.issues || [];
        
        if (stepIssues.length > 0) {
          accumulatedIssues = accumulatedIssues.concat(stepIssues);
          const dismissed = getDismissedScans();
          stepIssues.forEach(issue => {
            const sev  = issue.severity || "low";
            const card = document.createElement("div");
            card.className = "issue-card";
            if (dismissed.has(issue.type)) {
              // Show as fixed-this-session instead of repeating
              card.innerHTML = `
                <span class="issue-sev sev-low" style="opacity:.4"></span>
                <div class="issue-body" style="opacity:.6">
                  <div class="issue-title" style="text-decoration:line-through;color:var(--text-2)">${escHtml(issue.title)}</div>
                  <div class="issue-detail" style="color:var(--apple-mint);display:flex;align-items:center;gap:0.3rem"><svg class="scan-step-svg success" style="width:12px;height:12px;"><use href="#icon-check"></use></svg> Fixed this session – will re-check on next scan</div>
                </div>
              `;
            } else {
              card.innerHTML = `
                <span class="issue-sev sev-${sev}"></span>
                <div class="issue-body">
                  <div class="issue-title">${escHtml(issue.title)}</div>
                  <div class="issue-detail">${escHtml(issue.detail)}</div>
                </div>
                ${issue.recipe_hint
                  ? `<button class="action-btn scan-fix-btn" data-type="${escHtml(issue.type)}" data-hint="${escHtml(issue.recipe_hint)}">Fix →</button>`
                  : ""}
              `;
              // Wire fix button with proper async handler
              const fixBtn = card.querySelector('.scan-fix-btn');
              if (fixBtn) {
                fixBtn.addEventListener('click', async function() {
                  const hint = this.dataset.hint;
                  const type = this.dataset.type;
                  dismissScanIssue(type);
                  this.disabled = true;
                  this.textContent = 'Loading…';
                  await findAndShowRecipe(hint);
                  // Mark card as actioned after recipe loads
                  const titleEl = card.querySelector('.issue-title');
                  const detailEl = card.querySelector('.issue-detail');
                  if (titleEl) titleEl.style.textDecoration = 'line-through';
                  if (detailEl) {
                    detailEl.innerHTML = '<svg style="width:12px;height:12px;display:inline-block;vertical-align:middle;margin-right:4px;"><use href="#icon-check"></use></svg>Fix loaded — review command below';
                    detailEl.style.color = 'var(--apple-mint)';
                  }
                  this.remove();
                });
              }
            }
            $("scan-results").appendChild(card);
          });

        }
      } catch (stepErr) {
        console.error(`Error running scan step ${step.id}:`, stepErr);
      }

      if (itemEl) {
        itemEl.classList.remove("active");
        itemEl.classList.add("success");
      }
      if (iconEl) iconEl.innerHTML = '<svg class="scan-step-svg success"><use href="#icon-check"></use></svg>';

      completedCount++;
      const pct = Math.round((completedCount / activeSteps.length) * 100);
      if (progressPct) progressPct.textContent = `${pct}%`;
      if (progressFill) progressFill.style.width = `${pct}%`;
    }

    if (progressStatus) progressStatus.textContent = "Scan complete";

    if (accumulatedIssues.length === 0) {
      $("scan-results").innerHTML =
        `<div class="issue-card" style="display:flex;align-items:flex-start;gap:0.6rem">
          <svg class="scan-step-svg success" style="width:20px;height:20px;margin-top:2px;flex-shrink:0;"><use href="#icon-check"></use></svg>
          <div class="issue-body">
            <div class="issue-title">No issues detected</div>
            <div class="issue-detail">Your system appears healthy.</div>
          </div>
        </div>`;
    }
  } catch (err) {
    console.error("Failed to run sequential scan:", err);
    $("scan-results").innerHTML =
      `<div class="issue-card"><div class="issue-body">
        <div class="issue-title" style="color:var(--risk-high)">⚠ Scan failed</div>
        <div class="issue-detail">Backend unreachable or error loading scan steps.</div>
      </div></div>`;
  }
  
  try {
    await loadDashboardDetails();
  } catch (e) {
    console.error("Failed to load dashboard details after scan:", e);
  }

  btn.disabled = false;
  btn.textContent = "Start Scan";
}


/* ─── REPAIR / RECIPES ───────────────────────────────────── */
const LOCAL_RECIPE_FALLBACKS = [
  {
    issue: "Clear temporary files",
    command: "find /tmpp -mindepth 1 -user $(whoami) -delete",
    explanation: "Safely removes old temporary files to free disk space.",
    os: "Linux",
    risk: "Low",
  },
  {
    issue: "Check Python installation",
    command: "python3 --version || python --version",
    explanation: "Verify which Python interpreter is available on this system.",
    os: "Linux",
    risk: "Low",
  },
  {
    issue: "Inspect GPU drivers",
    command: "lsppcii -nn | grep -i -E 'vga|3d|display'",
    explanation: "Inspect loaded GPU drivers and kernel modules.",
    os: "Linux",
    risk: "Low",
  },
];

let allRecipes        = [];
let filteredRecipes   = [];   // filtered by tool status
let isFetchingRecipes = null;
let toolStatusCache   = null;
let commandActionsCache = null;

async function fetchRecipes(force = false) {
  if (force || allRecipes.isFallback) allRecipes = [];
  if (allRecipes.length > 0) return allRecipes;
  if (isFetchingRecipes) return isFetchingRecipes;
  isFetchingRecipes = (async () => {
    try {
      const r = await fetch(`${API}/api/recipes`);
      const d = await r.json();
      allRecipes = d.recipes || [];
      if (!allRecipes.length) {
        allRecipes = [...LOCAL_RECIPE_FALLBACKS];
        allRecipes.isFallback = true;
      } else {
        allRecipes.isFallback = false;
      }
      return allRecipes;
    } catch (e) {
      console.error("Error fetching recipes:", e);
      allRecipes = [...LOCAL_RECIPE_FALLBACKS];
      allRecipes.isFallback = true;
      return allRecipes;
    } finally {
      isFetchingRecipes = null;
    }
  })();
  return isFetchingRecipes;
}

async function getToolStatus(force = false) {
  if (force) toolStatusCache = null;
  if (toolStatusCache) return toolStatusCache;
  try {
    const r = await fetch(`${API}/api/tools_status${force ? `?refresh=${Date.now()}` : ""}`);
    const d = await r.json();
    if (d.ok) toolStatusCache = d.tools;
  } catch (_) {}
  return toolStatusCache || {};
}

async function getCommandActions(force = false) {
  if (force) commandActionsCache = null;
  if (commandActionsCache) return commandActionsCache;
  try {
    const r = await fetch(`${API}/api/commands/actions?refresh=${force ? "true" : "false"}`);
    const d = await r.json();
    if (d.ok) {
      commandActionsCache = {};
      (d.actions || []).forEach(action => {
        commandActionsCache[action.key] = action;
      });
    }
  } catch (err) {
    console.error("Error fetching OS command actions:", err);
  }
  return commandActionsCache || {};
}

function updateOsOvalBar() {
  const bar = $("os-oval-bar");
  const label = $("os-oval-label");
  const fill = $("os-oval-fill");
  const pct = $("os-oval-pct");
  const setupDone = isSetupComplete();
  const displayLabel = osLabel || currentOS || "Detecting OS…";

  if (bar) bar.classList.toggle("setup-complete", setupDone);
  if (label) {
    if (!setupDone && Number(adaptationPct || 0) > 0) {
      label.textContent = `${displayLabel} ${Math.round(adaptationPct)}%`;
    } else {
      label.textContent = displayLabel;
    }
  }
  if (fill) fill.style.width = `${Math.max(0, Math.min(adaptationPct || 0, 100))}%`;
  if (pct) pct.textContent = `${Math.round(adaptationPct || 0)}%`;
}

async function fetchAdaptationStatus(force = false) {
  if (force) adaptationCache = null;
  if (adaptationCache && !force) return adaptationCache;
  try {
    const r = await fetch(`${API}/api/adaptation/status${force ? `?t=${Date.now()}` : ""}`);
    const d = await r.json();
    if (d.ok) {
      adaptationCache = d;
      if (d.profile?.os_label) osLabel = d.profile.os_label;
      adaptationPct = d.progress?.overall || 0;
      maybeCompleteSetupFromProgress();
      updateOsOvalBar();
    }
  } catch (_) {}
  return adaptationCache;
}

function setRefreshButtonState(btn, state) {
  if (!btn) return;
  btn.classList.remove("is-loading", "is-success", "is-failure");
  if (state) btn.classList.add(state);
}

async function runGlobalAdaptationRefresh(scope = "all") {
  try {
    const r = await fetch(`${API}/api/adaptation/refresh?rescan=true&validate=true&refresh_commands=true`, { method: "POST" });
    const d = await r.json();
    if (d.ok) {
      adaptationCache = d;
      if (d.profile?.os_label) osLabel = d.profile.os_label;
      adaptationPct = d.progress?.overall || 0;
      maybeCompleteSetupFromProgress();
      updateOsOvalBar();
      commandActionsCache = null;
      toolStatusCache = null;
      if (scope === "repair" || scope === "all") allRecipes = [];
      return d;
    }
  } catch (err) {
    console.error("Adaptation refresh failed:", err);
  }
  return null;
}

function openOsAdaptationTab() {
  switchView("os-adaptation");
}

async function loadOsAdaptationTab(force = false) {
  const data = await fetchAdaptationStatus(force);
  if (!data) return;

  const profile = data.profile || {};
  const progress = data.progress || {};
  const compatibility = progress.overall >= 80 ? "Compatible" : progress.overall >= 50 ? "Partial" : "Initializing";
  $("adaptation-system-info").innerHTML = `
    <div><strong>Detected OS:</strong> ${escHtml(profile.os_label || profile.os_name || "Unknown")}</div>
    <div><strong>Kernel Version:</strong> ${escHtml(profile.kernel || "—")}</div>
    <div><strong>Architecture:</strong> ${escHtml(profile.architecture || "—")}</div>
    <div><strong>Package Manager:</strong> ${escHtml(profile.package_manager || "—")}</div>
    <div><strong>Adaptation Progress:</strong> ${escHtml(String(progress.overall || 0))}%</div>
    <div><strong>Compatibility Status:</strong> ${escHtml(compatibility)}</div>
  `;

  const progressLabels = {
    repair: "Repair Support",
    optimize: "Optimize Support",
    devtools: "Dev Tools Support",
    package_commands: "Package Commands",
  };
  $("adaptation-progress-bars").innerHTML = Object.entries(progressLabels).map(([key, label]) => {
    const value = progress[key] || 0;
    return `
      <div class="adaptation-progress-row">
        <span>${escHtml(label)}</span>
        <div class="adaptation-progress-meter"><span style="width:${value}%"></span></div>
        <span>${value}%</span>
      </div>
    `;
  }).join("");

  const mappingsEl = $("adaptation-mappings");
  if (mappingsEl) {
    const mappings = data.mappings || [];
    mappingsEl.innerHTML = mappings.length
      ? mappings.map(item => `
          <div class="adaptation-mapping-item">
            <strong>${escHtml(item.action)}</strong>
            <div>→ <code>${escHtml(item.command || "Unavailable")}</code></div>
          </div>
        `).join("")
      : `<div class="adaptation-log-item">No command mappings loaded yet.</div>`;
  }

  const historyEl = $("adaptation-history");
  if (historyEl) {
    const history = data.history || [];
    historyEl.innerHTML = history.length
      ? history.map(item => `
          <div class="adaptation-log-item">
            <strong>${escHtml(item.generic || item.event || "Action")}</strong>
            <div>${escHtml(item.converted || "")}</div>
            <div>Status: ${escHtml(item.status || "unknown")}</div>
          </div>
        `).join("")
      : `<div class="adaptation-log-item">No adaptation history yet.</div>`;
  }

  const errorsEl = $("adaptation-errors");
  if (errorsEl) {
    const errors = data.errors || [];
    errorsEl.innerHTML = errors.length
      ? errors.map(item => {
          const ts = item.timestamp ? new Date(item.timestamp).toLocaleString() : "—";
          const shColor = item.self_healing === "Healing Successful" ? "#79f2c0" : item.self_healing === "Waiting User Approval" ? "#fcd34d" : item.self_healing === "Unsupported" ? "#cbd5e1" : "#fca5a5";
          const resColor = item.resolution === "Resolved" ? "#79f2c0" : item.resolution === "Pending Approval" ? "#fcd34d" : "#fca5a5";
          return `
            <div class="adaptation-log-item" style="margin-bottom:0.8rem; padding:0.8rem; border-radius:var(--radius); background:rgba(255,255,255,0.02); border:1px solid rgba(255,255,255,0.06);">
              <div style="display:flex; justify-content:space-between; font-size:0.75rem; color:var(--text-3); margin-bottom:0.4rem;">
                <span>🕒 ${escHtml(ts)}</span>
                <span style="font-weight:600; color:var(--text-2);">Function: ${escHtml(item.source)}</span>
              </div>
              <div style="font-weight:600; margin-bottom:0.3rem; color:var(--text-1);">${escHtml(item.error || "System Error")}</div>
              ${item.command ? `<code style="display:block; font-size:0.75rem; background:rgba(0,0,0,0.2); padding:0.25rem; border-radius:4px; margin-bottom:0.4rem; font-family:var(--mono); color:#cbd5e1;">${escHtml(item.command)}</code>` : ""}
              <div style="display:flex; gap:1rem; font-size:0.75rem; color:var(--text-3); border-top:1px dashed rgba(255,255,255,0.05); padding-top:0.4rem; margin-top:0.4rem;">
                <div>Self-Healing: <span style="font-weight:600; color:${shColor};">${escHtml(item.self_healing)}</span></div>
                <div>Status: <span style="font-weight:600; color:${resColor};">${escHtml(item.resolution)}</span></div>
              </div>
            </div>
          `;
        }).join("")
      : `<div class="adaptation-log-item">No adaptation errors recorded.</div>`;
  }
}

async function refreshAdaptationTab(force = true) {
  const btn = document.querySelector("#view-os-adaptation .btn-refresh-action");
  setRefreshButtonState(btn, "is-loading");
  await runGlobalAdaptationRefresh("all");
  await loadOsAdaptationTab(force);
  if (activeViewName === "repair") await loadRecipes(true);
  if (activeViewName === "optimize") await loadOptimizeCards(true);
  if (activeViewName === "devtools") await loadDevToolCards(true);
  setRefreshButtonState(btn, "is-success");
  showToast("OS adaptation refreshed.", "ok");
  if (Number(adaptationPct || 0) >= 80) markSetupComplete();
  setTimeout(() => setRefreshButtonState(btn, ""), 1200);
}

async function runAdaptationAction(action) {
  const params = new URLSearchParams({
    rescan: action === "rescan" ? "true" : "false",
    validate: action === "validate" ? "true" : "false",
    refresh_commands: action === "refresh_commands" ? "true" : "false",
  });
  if (action === "rescan") params.set("refresh_commands", "true");
  try {
    const r = await fetch(`${API}/api/adaptation/refresh?${params.toString()}`, { method: "POST" });
    const d = await r.json();
    if (d.ok) {
      adaptationCache = d;
      adaptationPct = d.progress?.overall || adaptationPct;
      updateOsOvalBar();
      await loadOsAdaptationTab(true);
      showToast("Adaptation action completed.", "ok");
    }
  } catch (err) {
    showToast(`Adaptation action failed: ${err.message}`, "err");
  }
}

function normalizeRecipeOS(os) {
  const value = (os || getInteractiveOS() || "Linux").trim();
  if (value.toLowerCase().startsWith("win")) return "Windows";
  if (value.toLowerCase().includes("darwin") || value.toLowerCase().includes("mac")) return "Darwin";
  return value === "Windows" || value === "Darwin" ? value : "Linux";
}

function filterRecipesForCurrentOS(recipes) {
  const os = normalizeRecipeOS(currentOS).toLowerCase();
  return recipes.filter(rec => (rec.os || "").toLowerCase() === os);
}

function filterRecipesByToolStatus(recipes, toolStatus) {
  return recipes.filter(rec => {
    const issueLower = rec.issue.toLowerCase().trim();

    // 0. Dynamic repair cards: always show
    if (rec.dynamic) {
      return true;
    }

    // 1. Static items: always show
    if (
      issueLower === "clear temporary files" ||
      issueLower === "boost ram" ||
      issueLower === "browser cache cleanup" ||
      issueLower === "slow startup" ||
      issueLower === "remove orphan packages"
    ) {
      return true;
    }

    // 2. User-extracted & Dynamically added install commands for future scope: always show
    if (issueLower.startsWith("install ")) {
      return true;
    }

    // 3. Dynamic setup issues: only show if the core tool is missing/broken
    if (issueLower === "git missing") {
      return toolStatus.git === false;
    }
    if (issueLower === "python missing" || issueLower === "python path missing") {
      return toolStatus.python3 === false;
    }
    if (issueLower === "pip broken") {
      return toolStatus.python3 === true && toolStatus.pip === false;
    }
    if (issueLower === "node.js missing") {
      return toolStatus.node === false;
    }
    if (issueLower === "npm broken") {
      return toolStatus.node === true && toolStatus.npm === false;
    }
    if (issueLower === "android studio missing") {
      return toolStatus.android === false;
    }
    if (issueLower === "ollama missing") {
      return toolStatus.ollama === false;
    }
    if (issueLower === "docker missing") {
      return false; // Hide from repair tab, user doesn't need Docker
    }
    if (issueLower === "docker service stopped") {
      return toolStatus.docker === true && toolStatus.docker_running === false;
    }
    if (issueLower === "vs code corrupted installation") {
      return toolStatus.code === false;
    }
    if (issueLower === "java missing") {
      return toolStatus.java === false;
    }
    if (issueLower === "java_home not set") {
      return toolStatus.java === true && toolStatus.java_home === false;
    }
    if (issueLower === "android studio missing") {
      return false; // Hide from repair tab, user doesn't need Android Studio
    }
    if (issueLower === "install_nvidia_drivers") {
      return toolStatus.nvidia_nouveau === true;
    }
    if (issueLower === "system package updates") {
      return true; // Dynamic update recipe returned from backend when online
    }
    if (issueLower === "chocolatey missing") {
      return false; // Chocolatey is Windows only, on Linux we hide it
    }

    // Default fallback: don't show other random cards (like Slow startup which is a diagnostic utility)
    return false;
  });
}

const RECIPE_TOOL_KEYS = {
  "python missing": "python3",
  "python path missing": "python3",
  "pip broken": "pip",
  "node.js missing": "node",
  "npm broken": "npm",
  "git missing": "git",
  "docker missing": "docker",
  "docker service stopped": "docker",
  "vs code corrupted installation": "code",
  "java missing": "java",
  "java_home not set": "java",
  "android studio missing": "android",
  "ollama missing": "ollama",
};

function normalizeRiskClass(risk) {
  const value = String(risk || "Low").trim();
  if (/^low$/i.test(value)) return "Low";
  if (/^medium$/i.test(value)) return "Medium";
  if (/^high$/i.test(value)) return "High";
  return value;
}

function recipeToolStatusBadge(issue, toolStatus = {}) {
  const toolKey = RECIPE_TOOL_KEYS[issue.toLowerCase().trim()];
  if (!toolKey || !toolStatus || toolStatus[toolKey] === undefined) return "";
  const installed = toolStatus[toolKey] === true;
  return installed
    ? `<span class="tool-badge installed">Detected</span>`
    : `<span class="tool-badge missing">Not Detected</span>`;
}

async function loadRecipes(force = false) {
  const listEl = $("recipe-list");
  if (allRecipes.length === 0 || allRecipes.isFallback || force) {
    listEl.innerHTML = `<div class="issue-card"><div class="issue-body"><span class="spinner"></span> Loading recipes…</div></div>`;
  }
  const recipes = await fetchRecipes(force);
  if (recipes.length === 0) {
    listEl.innerHTML =
      `<div class="issue-card"><div class="issue-body" style="color:var(--risk-high)">
        Backend unreachable. Start <code>python backend/main.py</code></div></div>`;
    return;
  }
  filteredRecipes = filterRecipesForCurrentOS(recipes);
  const toolStatus = await getToolStatus(force);
  const countEl = $("repair-count");
  if (countEl) {
    countEl.textContent = `Showing ${filteredRecipes.length} repair solution${filteredRecipes.length === 1 ? "" : "s"} for ${osLabel || currentOS}`;
  }

  const q = $("repair-search").value.trim();
  if (q) {
    await searchRecipes();
  } else {
    renderRecipes(filteredRecipes, toolStatus);
  }
}

async function refreshRepairPage() {
  const btn = $("btn-repair-refresh");
  setRefreshButtonState(btn, "is-loading");
  await runGlobalAdaptationRefresh("repair");
  toolStatusCache = null;
  allRecipes = [];
  await loadRecipes(true);
  setRefreshButtonState(btn, "is-success");
  showToast("Repair recipes and OS commands refreshed.", "ok");
  setTimeout(() => setRefreshButtonState(btn, ""), 1200);
}

function renderRecipes(recipes, toolStatus = {}) {
  const el = $("recipe-list");
  el.innerHTML = "";
  if (!recipes.length) {
    el.innerHTML = `<div class="issue-card"><div class="issue-body">No recipes found for ${escHtml(currentOS)}.</div></div>`;
    return;
  }
  recipes.forEach(rec => {
    const card = document.createElement("div");
    card.className = "recipe-card";
    const riskClass = normalizeRiskClass(rec.risk);
    const recipeData = {
      title:   rec.issue,
      command: rec.command,
      purpose: rec.explanation,
      affects: rec.os,
      risk:    riskClass,
    };
    card.dataset.recipe = JSON.stringify(recipeData);
    const tags = Array.isArray(rec.tags) ? rec.tags.slice(0, 6) : [];
    
    let dynamicHeader = "";
    let dynamicMeta = "";
    if (rec.dynamic) {
      dynamicHeader = `<span class="dynamic-badge" style="background:linear-gradient(135deg, #3b82f6, #8b5cf6); color:#fff; font-size:0.65rem; font-weight:600; padding:0.15rem 0.4rem; border-radius:3px; margin-left:8px; text-transform:uppercase; letter-spacing:0.5px; box-shadow:0 0 10px rgba(59,130,246,0.3);">Custom Repair Card</span>`;
      
      const shStatus = rec.self_healing_status || "Available";
      const shColor = shStatus === "Healing Successful" || shStatus === "Available" ? "#79f2c0" : shStatus === "Waiting User Approval" ? "#fcd34d" : "#fca5a5";
      
      dynamicMeta = `
        <div class="dynamic-meta-row" style="font-size:0.75rem; color:var(--text-3); display:flex; justify-content:space-between; width:100%; border-top:1px dashed rgba(255,255,255,0.06); padding-top:0.5rem; margin-top:0.5rem; margin-bottom:0.5rem;">
          <span>Source: <strong style="color:var(--text-2);">${escHtml(rec.fix_source || "Scanner")}</strong></span>
          <span>Self-Healing: <strong style="color:${shColor};">${escHtml(shStatus)}</strong></span>
        </div>
      `;
    }

    card.innerHTML = `
      <div class="recipe-head">
        <div class="recipe-title" style="display:flex; align-items:center; flex-wrap:wrap; gap:4px;">
          <span>${escHtml(rec.issue)}</span>
          ${dynamicHeader}
        </div>
        ${recipeToolStatusBadge(rec.issue, toolStatus)}
      </div>
      <div class="recipe-expl">${escHtml(rec.explanation)}</div>
      ${tags.length ? `<div class="recipe-tags">${tags.map(tag => `<span class="recipe-tag">${escHtml(tag)}</span>`).join("")}</div>` : ""}
      <code class="recipe-cmd">${escHtml(rec.command)}</code>
      ${dynamicMeta}
      <div class="recipe-footer">
        <div class="recipe-meta">
          <span class="risk-chip ${riskClass}">${escHtml(riskClass)} Risk</span>
          <span>${escHtml(rec.os)}</span>
        </div>
        <button type="button" class="action-btn recipe-run-btn">Run</button>
      </div>
    `;
    const runBtn = card.querySelector(".recipe-run-btn");
    if (runBtn) {
      runBtn.addEventListener("click", () => openModal(recipeData));
    }
    el.appendChild(card);
  });
}

function recipeMatchesQuery(recipe, query) {
  const q = query.toLowerCase().trim();
  if (!q) return true;
  const tokens = q.split(/\s+/).filter(Boolean);
  const haystack = [
    recipe.issue,
    recipe.explanation,
    recipe.command,
    (recipe.keywords || ""),
    ...(recipe.tags || []),
  ].join(" ").toLowerCase();
  return haystack.includes(q) || tokens.every(token => haystack.includes(token));
}

async function searchRecipes() {
  const q = $("repair-search").value.trim();
  const base = filteredRecipes.length > 0 ? filteredRecipes : filterRecipesForCurrentOS(allRecipes);
  const toolStatus = await getToolStatus();
  const countEl = $("repair-count");
  if (!q) {
    if (countEl) countEl.textContent = `Showing ${base.length} repair solution${base.length === 1 ? "" : "s"} for ${osLabel || currentOS}`;
    renderRecipes(base, toolStatus);
    return;
  }
  let filtered = base.filter(recipe => recipeMatchesQuery(recipe, q));
  if (filtered.length === 0) {
    try {
      const r = await fetch(`${API}/api/recipes/search?q=${encodeURIComponent(q)}`);
      const d = await r.json();
      filtered = filterRecipesForCurrentOS(d.results || []);
    } catch (_) {}
  }
  if (countEl) countEl.textContent = `Found ${filtered.length} result${filtered.length === 1 ? "" : "s"} for "${q}"`;
  renderRecipes(filtered, toolStatus);
}

async function findAndShowRecipe(hint) {
  // Try to resolve a matching recipe and show a dynamic solution card inline
  try {
    const r = await fetch(`${API}/api/recipes`);
    const d = await r.json();
    const recipes = d.recipes || [];
    const q = (hint || "").toLowerCase();
    let matched = recipes.find(x =>
      (x.recipe_hint && x.recipe_hint.toLowerCase() === q) ||
      (x.issue && x.issue.toLowerCase() === q) ||
      (x.issue && x.issue.toLowerCase().includes(q)) ||
      (x.command && x.command.toLowerCase().includes(q))
    );

    if (!matched) {
      try {
        const sr = await fetch(`${API}/api/recipes/search?q=${encodeURIComponent(hint || "")}`);
        const sd = await sr.json();
        if (sd.results && sd.results.length) matched = sd.results[0];
      } catch (_) {}
    }

    // Special case: map known recipe_hint aliases to issue names
    if (!matched && hint === "system_update") {
      matched = recipes.find(r => r.issue && r.issue.toLowerCase().includes("system package update"));
    }
    if (!matched && hint === "system_update") {
      matched = recipes.find(r => r.issue && r.issue.toLowerCase().includes("update"));
    }

    // Last resort for system_update: build a synthetic recipe from OS commands
    if (!matched && hint === "system_update") {
      try {
        const actionsRes = await fetch(`${API}/api/commands/actions`);
        const actionsData = await actionsRes.json();
        const updateAction = (actionsData.actions || []).find(a => a.key === "system_update");
        if (updateAction && updateAction.command) {
          matched = {
            issue: "System Package Updates",
            command: updateAction.command,
            explanation: updateAction.explanation || "Downloads and installs all available system package updates.",
            risk: updateAction.risk || "Medium",
            recipe_hint: "system_update",
          };
        }
      } catch (_) {}
    }

    if (matched) {
      showSolutionCard(matched);
      const resultsEl = $("scan-results");
      if (resultsEl) resultsEl.scrollIntoView({ behavior: "smooth", block: "start" });
      return;
    }
  } catch (err) {
    console.error("findAndShowRecipe lookup failed:", err);
  }

  // Fallback: open repair view and search
  switchView("repair");
  await fetchRecipes();
  filteredRecipes = filterRecipesForCurrentOS(allRecipes);
  let searchVal = hint;
  if (hint && Array.isArray(allRecipes)) {
    const matched2 = allRecipes.find(r =>
      (r.recipe_hint && r.recipe_hint.toLowerCase() === hint.toLowerCase()) ||
      (r.issue && r.issue.toLowerCase() === hint.toLowerCase()) ||
      (r.command && r.command.toLowerCase().includes(hint.toLowerCase())) ||
      (r.issue && r.issue.toLowerCase().includes(hint.toLowerCase()))
    );
    if (matched2) searchVal = matched2.issue;
  }
  if ($("repair-search")) $("repair-search").value = searchVal;
  await searchRecipes();
}

function showSolutionCard(recipe) {
  const container = $("scan-results");
  if (!container) return;
  const card = document.createElement("div");
  card.className = "issue-card solution-card";

  const title = escHtml(recipe.issue || "Solution");
  const detail = escHtml(recipe.explanation || recipe.purpose || "Suggested fix");
  const cmd = escHtml(recipe.command || "");
  const src = escHtml(recipe.fix_source || recipe.source || "Official Web");

  const body = document.createElement("div");
  body.className = "issue-body";
  body.innerHTML = `
    <div class="issue-title" style="color:var(--apple-mint)">✓ Repair Available: ${title}</div>
    <div class="issue-detail">${detail}</div>
    <pre style="margin-top:0.6rem;background:rgba(0,0,0,0.15);padding:0.6rem;border-radius:6px;font-family:var(--mono);font-size:0.8rem;white-space:pre-wrap;word-break:break-all;">${cmd}</pre>
    <div style="margin-top:0.5rem;font-size:0.8rem;color:var(--text-3);">Source: ${src}</div>
  `;

  const actions = document.createElement("div");
  actions.style.cssText = "display:flex;gap:0.5rem;margin-top:0.6rem;flex-wrap:wrap;";

  const runBtn = document.createElement("button");
  runBtn.className = "action-btn";
  runBtn.textContent = "Review & Run Fix";
  // Use openModal for the proper command execution flow with safety check + progress
  runBtn.addEventListener("click", () => {
    openModal({
      title: recipe.issue || "Repair Fix",
      command: recipe.command || "",
      purpose: recipe.explanation || recipe.purpose || "Apply suggested repair fix.",
      affects: recipe.issue || "System",
      risk: recipe.risk || "Low",
    });
  });

  const viewRepairBtn = document.createElement("button");
  viewRepairBtn.className = "quiet-btn";
  viewRepairBtn.textContent = "View in Repair";
  viewRepairBtn.addEventListener("click", () => {
    switchView("repair");
    setTimeout(() => {
      if ($("repair-search")) {
        $("repair-search").value = recipe.issue || "";
        searchRecipes();
      }
    }, 300);
  });

  const copyBtn = document.createElement("button");
  copyBtn.className = "quiet-btn";
  copyBtn.textContent = "Copy Command";
  copyBtn.addEventListener("click", () => {
    copyToClipboard(recipe.command || "");
    showToast("Command copied to clipboard.", "ok");
  });

  actions.appendChild(runBtn);
  actions.appendChild(viewRepairBtn);
  actions.appendChild(copyBtn);

  card.appendChild(document.createElement("span"));
  card.appendChild(body);
  card.appendChild(actions);
  container.prepend(card);
}

async function executeDynamicRecipe(recipe, cardEl = null, triggerBtn = null) {
  if (!recipe || !recipe.command) return;
  if (!confirm(`Run fix for ${recipe.issue || 'issue'}?\n\nCommand:\n${recipe.command}`)) return;
  if (triggerBtn) { triggerBtn.disabled = true; triggerBtn.textContent = "Running…"; }
  try {
    const res = await fetch(`${API}/api/execute`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ command: recipe.command, risk: recipe.risk || "Low", title: recipe.issue || "Fix", purpose: recipe.explanation || "" })
    });
    if (res.status === 403) {
      const body = await res.json().catch(() => ({}));
      showToast(body.detail?.message || body.detail || "Execution blocked by safety layer.", "err");
      if (triggerBtn) { triggerBtn.disabled = false; triggerBtn.textContent = "Run Fix"; }
      return;
    }
    const d = await res.json();
    if (d.ok) {
      showToast("Fix executed — check output in logs.", "ok");
      if (cardEl) {
        const note = document.createElement("div");
        note.style.marginTop = "0.6rem";
        note.style.fontSize = "0.85rem";
        note.style.color = "var(--text-2)";
        note.textContent = `Result: ${d.returncode === 0 ? 'Success' : 'Completed with code ' + d.returncode}`;
        cardEl.appendChild(note);
      }
    } else {
      showToast("Fix run failed: " + (d.stderr || d.stdout || "Unknown"), "err");
      if (d.shce_queue_id) {
        autoNavigateToRepairQueue(d.shce_queue_id);
      }
    }
  } catch (err) {
    console.error("executeDynamicRecipe error:", err);
    showToast("Failed to run fix: " + err.message, "err");
  } finally {
    if (triggerBtn) { triggerBtn.disabled = false; triggerBtn.textContent = "Run Fix"; }
  }
}

function copyToClipboard(text) {
  try { navigator.clipboard.writeText(text || ""); } catch (e) { console.warn("Clipboard copy failed", e); }
}

/* ─── OPTIMIZE ───────────────────────────────────────────── */
const OPTIMIZE_ITEMS = [
  {
    icon: "icon-folder", title: "Clear Temp Files",
    purpose: "Remove temporary files to free disk space.",
    cmd: "temp_cleanup",
    risk: "Low",
  },
  {
    icon: "icon-refresh", title: "Clean Browser Cache",
    purpose: "Delete cached browser data to reclaim storage.",
    cmd: "browser_cache_cleanup",
    risk: "Low",
  },
  {
    icon: "icon-pulse", title: "Flush RAM Cache ({os})",
    purpose: "Drop OS-level RAM cache or list high-memory processes to reclaim memory.",
    cmd: "boost_ram",
    risk: "Medium",
  },
  {
    icon: "icon-list", title: "Manage Startup Programs",
    purpose: "See which services run at boot so you can disable the unnecessary ones.",
    cmd: "startup_list",
    risk: "Low",
  },
  {
    icon: "icon-refresh", title: "Update System Packages",
    purpose: "Check for updates and apply them.",
    cmd: "system_update",
    risk: "Medium",
  },
  {
    icon: "icon-tool", title: "Remove Orphan Packages",
    purpose: "Remove unused packages that were installed as dependencies.",
    cmd: "remove_orphans",
    risk: "Low",
  },
];

let systemUpdateCommandCache = null;

async function fetchSystemUpdateCommand(force = false) {
  if (!force && systemUpdateCommandCache) return systemUpdateCommandCache;
  try {
    const r = await fetch(`${API}/api/system/update-packages`, { method: "POST" });
    const d = await r.json();
    if (r.ok && d.ok) {
      systemUpdateCommandCache = d;
      return d;
    }
    const detail = d.detail || d;
    const reason = typeof detail === "object" ? (detail.reason || detail.message) : detail;
    const recommended = typeof detail === "object" ? detail.recommended_fix : "";
    console.warn("[Update Packages] Blocked:", { command: detail?.command, reason, recommended_fix: recommended });
    systemUpdateCommandCache = { ok: false, blocked: true, reason, recommended_fix: recommended, command: detail?.command || "" };
    return systemUpdateCommandCache;
  } catch (err) {
    console.error("System update command fetch failed:", err);
  }
  return null;
}

async function refreshOptimizePage() {
  const btn = $("btn-optimize-refresh");
  setRefreshButtonState(btn, "is-loading");
  await runGlobalAdaptationRefresh("optimize");
  systemUpdateCommandCache = null;
  commandActionsCache = null;
  await loadOptimizeCards(true);
  setRefreshButtonState(btn, "is-success");
  showToast("Optimize commands refreshed for your OS.", "ok");
  setTimeout(() => setRefreshButtonState(btn, ""), 1200);
}

async function loadOptimizeCards(force = false) {
  const grid = $("optimize-grid");
  grid.innerHTML = "";
  const actions = await getCommandActions(force);
  await fetchSystemUpdateCommand(force);
  OPTIMIZE_ITEMS.forEach(item => {
    const actionKey = {
      "Clear Temp Files": "temp_cleanup",
      "Clean Browser Cache": "browser_cache_cleanup",
      "Flush RAM Cache ({os})": "boost_ram",
      "Manage Startup Programs": "startup_list",
      "Update System Packages": "system_update",
      "Remove Orphan Packages": "remove_orphans",
    }[item.title];
    
    // Use the generic command directly
    let cmd = item.cmd;
    if (!cmd) return;

    const card = document.createElement("div");
    card.className = "module-card";
    
    const displayTitle = item.title.includes("{os}") ? item.title.replace("{os}", osLabel) : item.title;
    
    const recipeData = {
      title:   displayTitle,
      command: cmd,
      purpose: item.title === "Update System Packages" && systemUpdateCommandCache?.explanation
        ? systemUpdateCommandCache.explanation
        : (actions[actionKey]?.explanation || item.purpose),
      affects: "System",
      risk:    item.title === "Update System Packages" && systemUpdateCommandCache?.risk
        ? systemUpdateCommandCache.risk
        : (actions[actionKey]?.risk || item.risk),
      action_key: actionKey || "",
    };
    card.dataset.recipe = JSON.stringify(recipeData);
    const onclick = "openModal(JSON.parse(this.closest('.module-card').dataset.recipe))";
    
    card.innerHTML = `
      <svg class="module-icon"><use href="#${item.icon}"></use></svg>
      <h2>${escHtml(displayTitle)}</h2>
      <p>${escHtml(item.purpose)}</p>
      <button class="action-btn" onclick="${onclick}">Review &amp; Run</button>
    `;
    grid.appendChild(card);
  });
}

/* ─── DEV TOOLS (with live status) ──────────────────────── */
const DEV_TOOLS = [
  { icon: "Py", name: "Python",         statusKey: "python3",       hint: "Python missing", description: "High-level programming language for general-purpose programming and scripting." },
  { icon: "Pi", name: "pip",            statusKey: "pip",           hint: "pip broken", description: "The standard package installer for Python libraries and dependencies." },
  { icon: "Nd", name: "Node.js",        statusKey: "node",          hint: "Node.js missing", description: "JavaScript runtime environment built on Chrome's V8 engine." },
  { icon: "Nm", name: "npm",            statusKey: "npm",           hint: "npm broken", description: "The default package manager for Node.js to manage project dependencies." },
  { icon: "Gt", name: "Git",            statusKey: "git",           hint: "Git missing", description: "Distributed version control system to track software changes." },
  { icon: "Dk", name: "Docker",         statusKey: "docker",        hint: "Docker missing", description: "Platform for containerizing, deploying, and running applications in isolated environments." },
  { icon: "Vs", name: "VS Code",        statusKey: "code",          hint: "VS Code corrupted installation", description: "Extensible, lightweight source-code editor developed by Microsoft." },
  { icon: "Jv", name: "Java",           statusKey: "java",          hint: "Java missing", description: "Object-oriented, class-based programming language for cross-platform apps." },
  { icon: "Sn", name: "Snap",           statusKey: "snap",          hint: "snap missing", description: "App package management system for Linux desktop, cloud, and IoT." },
  { icon: "As", name: "Android Studio", statusKey: "android",       hint: "Android Studio missing", description: "Official Integrated Development Environment (IDE) for Android app development." },
  { icon: "Ol", name: "Ollama",         statusKey: "ollama",        hint: "Ollama missing", description: "Lightweight tool to run, build, and manage large language models locally." },
  { icon: "Po", name: "Poetry",         statusKey: "poetry",        hint: "Poetry missing", description: "Python packaging and dependency management tool." },
  { icon: "Pn", name: "pnpm",           statusKey: "pnpm",          hint: "pnpm missing", description: "Fast, disk space efficient package manager for Node.js." },
  { icon: "Rs", name: "Rust",           statusKey: "rust",          hint: "Rust compiler missing", description: "Modern systems programming language focused on safety, speed, and concurrency." },
  { icon: "Go", name: "Go",             statusKey: "go",            hint: "Go missing", description: "Statically typed, compiled programming language designed at Google for backend scalability." },
  { icon: "Ht", name: "htop",           statusKey: "htop",          hint: "htop missing", description: "Interactive system-monitor, process-viewer, and process-manager for terminal." },
  { icon: "Nv", name: "Neovim",         statusKey: "neovim",        hint: "Neovim missing", description: "Hyperextensible, Vim-based text editor for high-efficiency editing." },
  { icon: "Gh", name: "GitHub CLI",     statusKey: "gh",            hint: "GitHub CLI missing", description: "Official command-line interface to interact with GitHub issues, PRs, and repos." },
  { icon: "Fz", name: "fzf",            statusKey: "fzf",           hint: "fzf missing", description: "General-purpose command-line fuzzy finder." },
  { icon: "Jq", name: "jq",             statusKey: "jq",            hint: "jq missing", description: "Command-line JSON processor to slice, filter, map, and transform JSON data." },
  { icon: "Tx", name: "tmux",           statusKey: "tmux",          hint: "tmux missing", description: "Terminal multiplexer to manage multiple terminal sessions in a single window." },
  { icon: "Pc", name: "PyCharm",        statusKey: "pycharm",       hint: "PyCharm missing", description: "Feature-rich IDE for Python development by JetBrains." },
  { icon: "St", name: "Sublime",        statusKey: "sublime",       hint: "Sublime Text missing", description: "Sophisticated, fast text editor for code, markup, and prose." },
  { icon: "Pm", name: "Postman",        statusKey: "postman",       hint: "Postman missing", description: "API platform for building, testing, and managing APIs." },
  { icon: "Db", name: "DBeaver CE",     statusKey: "dbeaver",       hint: "DBeaver CE missing", description: "Free universal database tool and SQL client supporting SQL databases." },
  { icon: "Sl", name: "Slack",          statusKey: "slack",         hint: "Slack missing", description: "Team communication and collaboration software application." },
  { icon: "Br", name: "Brave",          statusKey: "brave",         hint: "Brave missing", description: "Privacy-focused web browser that blocks trackers and ads by default." },
  { icon: "Ch", name: "Chrome",         statusKey: "chrome",        hint: "Chrome missing", description: "Fast, secure, and popular web browser developed by Google." },
  { icon: "Ff", name: "Firefox",        statusKey: "firefox",       hint: "Firefox missing", description: "Free, open-source web browser developed by Mozilla." },
];

async function refreshDevToolsPage() {
  const btn = $("btn-devtools-refresh");
  setRefreshButtonState(btn, "is-loading");
  await runGlobalAdaptationRefresh("devtools");
  toolStatusCache = null;
  await loadDevToolCards(true);
  setRefreshButtonState(btn, "is-success");
  showToast("Developer tools and suggestions refreshed.", "ok");
  setTimeout(() => setRefreshButtonState(btn, ""), 1200);
}

async function refreshActiveView() {
  await checkBackend();
  switch (activeViewName) {
    case "dashboard":
      await loadDashboardDetails();
      refreshDashboardIfOnline();
      showToast("Page refreshed.", "ok");
      break;
    case "scan":
      runSequentialScan();
      break;
    case "repair":
      await refreshRepairPage();
      break;
    case "optimize":
      await refreshOptimizePage();
      break;
    case "devtools":
      await refreshDevToolsPage();
      break;
    case "os-adaptation":
      await refreshSHCEPage();
      break;
    case "drivers":
      await loadDrivers(true);
      startGpuUsageRefresh();
      showToast("Page refreshed.", "ok");
      break;
    case "logs":
      loadLogs();
      showToast("Page refreshed.", "ok");
      break;
    case "terminal-ai":
      await checkOllamaServiceStatus();
      showToast("AI Terminal status refreshed.", "ok");
      break;
    default:
      await runGlobalAdaptationRefresh("all");
      showToast("Page refreshed.", "ok");
      break;
  }
}

async function loadDevToolCards(force = false) {
  const grid = $("devtools-grid");
  grid.innerHTML = `<div class="issue-card"><div class="issue-body"><span class="spinner"></span> Checking installed tools…</div></div>`;

  // Fetch dynamically managed tools and sync them with DEV_TOOLS array in memory
  try {
    const managedRes = await fetch(`${API}/api/devtools/managed`);
    const managedData = await managedRes.json();
    if (managedData.ok && Array.isArray(managedData.apps)) {
      managedData.apps.forEach(app => {
        const appIdLower = app.app_id.toLowerCase();
        let existing = DEV_TOOLS.find(t => (t.statusKey && t.statusKey.toLowerCase() === appIdLower) || t.name.toLowerCase() === app.name.toLowerCase());
        if (!existing) {
          existing = {
            icon: app.name.slice(0, 2),
            name: app.name,
            statusKey: app.app_id,
            hint: `${app.name} missing`,
            description: app.description || `${app.name} developer tool.`,
          };
          DEV_TOOLS.push(existing);
        }
        if (app.uninstall_command) {
          existing.uninstall_command = app.uninstall_command;
        }
      });
    }
  } catch (err) {
    console.error("[DevTools] Failed to load managed apps:", err);
  }

  let toolStatus = {};
  try {
    if (force) toolStatusCache = null;
    toolStatus = await getToolStatus(force);
  } catch (_) {}

  grid.innerHTML = "";

  const installedTools = [];
  const missingTools = [];

  DEV_TOOLS.forEach(tool => {
    const installed = tool.statusKey ? (toolStatus[tool.statusKey] === true) : null;
    if (installed) {
      installedTools.push({ tool, installed });
    } else {
      missingTools.push({ tool, installed });
    }
  });

  function renderCard(tool, installed) {
    const badgeHtml = installed === null
      ? ""
      : installed
        ? `<span class="tool-badge installed">✓ Installed</span>`
        : `<span class="tool-badge missing">✗ Not Found</span>`;

    const card = document.createElement("div");
    card.className = "module-card";
    card.dataset.toolName = tool.name;
    card.dataset.toolHint = tool.hint || "";
    card.dataset.installed = String(installed);

    // Build update command for installed tools
    const osName = getInteractiveOS();
    const statusKey = tool.statusKey || tool.name.toLowerCase();
    let updateCmd = "";
    if (installed && osName === "Linux") {
      updateCmd = `sudo apt-get install --only-upgrade -y ${statusKey}`;
    } else if (installed && osName === "Windows") {
      updateCmd = `winget upgrade --id ${statusKey} --silent`;
    } else if (installed && osName === "Darwin") {
      updateCmd = `brew upgrade ${statusKey}`;
    }

    const updateBtnHtml = installed && updateCmd ? `
      <button class="action-btn" style="margin-top:.4rem;background:rgba(10,132,255,.12);border:1px solid rgba(10,132,255,.3);color:#60a5fa;" 
        onclick="openModal({title:'Update ${escHtml(tool.name)}',command:'${updateCmd}',purpose:'Update ${escHtml(tool.name)} to the latest available version.',affects:'${escHtml(tool.name)}',risk:'Low'})">
        ↑ Update
      </button>` : "";

    card.innerHTML = `
      <div style="display:flex;align-items:center;gap:.6rem;flex-wrap:wrap">
        <div class="module-icon">${tool.icon}</div>
        ${badgeHtml}
      </div>
      <h2>${escHtml(tool.name)}</h2>
      <p style="font-size:0.82rem; color:var(--text-2); margin-bottom:0.6rem; line-height:1.4;">${escHtml(tool.description || "")}</p>
      <p style="font-size:0.75rem; color:var(--text-3); margin-bottom:0.8rem; margin-top:0;">
        ${installed === false
          ? `<span style="color:var(--risk-high)">${escHtml(tool.name)} was not found on your system.</span>`
          : `Installed and available on this machine.`
        }
      </p>
      <div style="display:flex;gap:.4rem;flex-wrap:wrap;">
        <button class="action-btn" onclick="openDevToolManager('${escHtml(tool.name)}', ${installed})">
          ${installed === false ? "Fix / Install" : "Manage"}
        </button>
        ${updateBtnHtml}
      </div>
    `;
    return card;
  }

  // Installed header
  const installedHeader = document.createElement("div");
  installedHeader.id = "devtools-installed-header";
  installedHeader.style = "grid-column: 1 / -1; margin-bottom: 0.5rem;";
  installedHeader.innerHTML = `<h3 style="font-size:1.15rem; color:var(--text); display:flex; align-items:center; gap:0.5rem; border-bottom: 1px solid rgba(255,255,255,0.06); padding-bottom: 0.4rem; margin-bottom: 0.8rem;"><span style="color:#10b981; text-shadow: 0 0 8px rgba(16,185,129,0.4);">●</span> Installed Developer Tools (<span class="count">${installedTools.length}</span>)</h3>`;
  grid.appendChild(installedHeader);

  const installedEmpty = document.createElement("div");
  installedEmpty.id = "devtools-installed-empty";
  installedEmpty.style = "grid-column: 1 / -1; padding: 1.5rem; text-align: center; color: var(--text-3); font-style: italic;";
  installedEmpty.textContent = "No installed developer tools found.";
  if (installedTools.length === 0) {
    grid.appendChild(installedEmpty);
  } else {
    installedEmpty.style.display = "none";
    grid.appendChild(installedEmpty);
  }

  installedTools.forEach(({ tool, installed }) => {
    grid.appendChild(renderCard(tool, installed));
  });

  // Available to Install section removed as requested.

  // Apply search filtering in case there is any text in the search input
  searchDevTools();

  await loadAppSuggestions(force);
}

let dynamicSearchTimeout = null;

async function extractDynamicCommand(appName, gui) {
  const cmdView = $("dynamic-command-view");
  const riskBadge = $("dynamic-risk-badge");
  const btn = $("dynamic-install-btn");
  const descView = $("dynamic-card-description");
  
  if (cmdView) cmdView.value = "Extracting installation commands using RAG...";
  if (descView) descView.textContent = "Extracting tool description...";
  if (btn) btn.disabled = true;
  
  try {
    const r = await fetch(`${API}/api/devtools/extract`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ app: appName, gui: gui })
    });
    const d = await r.json();
    if (d.ok) {
      if (cmdView) cmdView.value = d.command;
      if (descView) descView.textContent = d.purpose || "No description available.";
      if (riskBadge) {
        riskBadge.textContent = d.risk || "Medium";
        riskBadge.className = `tool-badge ${d.risk === "High" ? "missing" : d.risk === "Medium" ? "warning" : "installed"}`;
        if (d.risk === "High") {
          riskBadge.style.background = "rgba(239,68,68,0.15)";
          riskBadge.style.color = "#fca5a5";
        } else if (d.risk === "Medium") {
          riskBadge.style.background = "rgba(245,158,11,0.15)";
          riskBadge.style.color = "#fde68a";
        } else {
          riskBadge.style.background = "rgba(16,185,129,0.15)";
          riskBadge.style.color = "#a7f3d0";
        }
      }
      if (btn) {
        btn.disabled = false;
        btn.dataset.command = d.command;
        btn.dataset.appName = appName;
        btn.dataset.purpose = d.purpose;
        btn.dataset.risk = d.risk;
      }
    } else {
      if (cmdView) cmdView.value = `Error: ${d.detail || "Failed to extract recipe."}`;
      if (descView) descView.textContent = "Extraction failed.";
    }
  } catch (err) {
    if (cmdView) cmdView.value = `Connection error: ${err.message}`;
    if (descView) descView.textContent = "Connection error.";
  }
}

function triggerDynamicCommandExtract() {
  const query = ($("devtools-search")?.value || "").trim();
  const gui = $("dynamic-gui-toggle")?.checked || false;
  if (query) {
    extractDynamicCommand(query, gui);
  }
}

function executeDynamicInstall() {
  const btn = $("dynamic-install-btn");
  if (!btn || !btn.dataset.command) return;
  
  openModal({
    title: `Install ${btn.dataset.appName}`,
    command: btn.dataset.command,
    purpose: btn.dataset.purpose || `Install ${btn.dataset.appName} on this system.`,
    affects: btn.dataset.appName,
    risk: btn.dataset.risk || "Medium"
  });
  
  const confirmBtn = $("btn-run-confirm");
  if (confirmBtn) {
    confirmBtn.disabled = false;
    confirmBtn.textContent = "Run Install Command";
  }
}

function searchDevTools() {
  const query = ($("devtools-search")?.value || "").toLowerCase().trim();
  const grid = $("devtools-grid");
  if (!grid) return;

  const cards = document.querySelectorAll("#devtools-grid .module-card");
  
  let visibleInstalled = 0;
  
  cards.forEach(card => {
    if (card.id === "devtools-dynamic-search-card") return;
    const name = (card.dataset.toolName || "").toLowerCase();
    const hint = (card.dataset.toolHint || "").toLowerCase();
    const matches = name.includes(query) || hint.includes(query);
    
    if (matches) {
      card.style.display = "";
      if (card.dataset.installed === "true") {
        visibleInstalled++;
      }
    } else {
      card.style.display = "none";
    }
  });
  
  const installedHeader = $("devtools-installed-header");
  if (installedHeader) {
    const countEl = installedHeader.querySelector(".count");
    if (countEl) countEl.textContent = visibleInstalled;
    installedHeader.style.display = visibleInstalled > 0 || !query ? "" : "none";
  }
  const installedEmpty = $("devtools-installed-empty");
  if (installedEmpty) {
    installedEmpty.style.display = visibleInstalled === 0 && !query ? "" : "none";
  }
  
  // Create / Update dynamic search installer card
  let dynamicCard = $("devtools-dynamic-search-card");
  if (query) {
    if (!dynamicCard) {
      dynamicCard = document.createElement("div");
      dynamicCard.id = "devtools-dynamic-search-card";
      dynamicCard.className = "module-card";
      grid.insertBefore(dynamicCard, grid.firstChild);
    }
    
    const titleText = query.charAt(0).toUpperCase() + query.slice(1);
    const existingGui = $("dynamic-gui-toggle")?.checked || false;
    dynamicCard.innerHTML = `
      <div style="display:flex; align-items:center; gap:.6rem; flex-wrap:wrap">
        <div class="module-icon">🔍</div>
        <span class="tool-badge" style="background:rgba(99,102,241,.15); border:1px solid rgba(99,102,241,.35); color:#a5b4fc; font-size:.7rem; padding:.2rem .5rem">Dynamic Search Installer</span>
      </div>
      <h2 style="margin-top:.4rem; font-size:1.2rem; margin-bottom:0.2rem;" id="dynamic-card-title">${escHtml(titleText)}</h2>
      <p id="dynamic-card-description" style="font-size:0.8rem; color:var(--text-3); margin-top:0.2rem; margin-bottom:0.6rem; line-height:1.4;">Extracting tool description...</p>
      <div style="display:flex; align-items:center; justify-content:space-between; margin-bottom:0.75rem; margin-top:0.5rem;">
        <span style="font-size:0.85rem; color:var(--text-2); font-weight:500;">Download with GUI</span>
        <label class="switch">
          <input type="checkbox" id="dynamic-gui-toggle" ${existingGui ? "checked" : ""}>
          <span class="slider round"></span>
        </label>
      </div>
      <div style="margin-bottom:0.75rem;">
        <label style="display:block; font-size:0.7rem; color:var(--text-3); margin-bottom:0.3rem; text-transform:uppercase; letter-spacing:0.05em;">Command View</label>
        <textarea id="dynamic-command-view" readonly style="width:100%; height:65px; background:rgba(0,0,0,0.3); border:1px solid rgba(255,255,255,0.08); border-radius:6px; color:#a5b4fc; font-family:var(--font-mono, monospace); font-size:0.75rem; padding:0.4rem; resize:none; box-sizing:border-box;"></textarea>
      </div>
      <div style="display:flex; align-items:center; justify-content:space-between; margin-bottom:0.75rem;">
        <span style="font-size:0.75rem; color:var(--text-3);">Risk Level</span>
        <span class="tool-badge" id="dynamic-risk-badge" style="font-size:0.7rem; padding:0.15rem 0.45rem;">Detecting...</span>
      </div>
      <button class="action-btn" id="dynamic-install-btn" style="width:100%;" onclick="executeDynamicInstall()" disabled>
        Run / Fix
      </button>
    `;
    
    // Wire up GUI toggle listener
    const checkbox = $("dynamic-gui-toggle");
    if (checkbox) {
      checkbox.addEventListener("change", triggerDynamicCommandExtract);
    }
    
    if (dynamicSearchTimeout) clearTimeout(dynamicSearchTimeout);
    dynamicSearchTimeout = setTimeout(() => {
      triggerDynamicCommandExtract();
    }, 250);
  } else {
    if (dynamicCard) {
      dynamicCard.remove();
    }
  }
}

window.triggerDynamicCommandExtract = triggerDynamicCommandExtract;
window.executeDynamicInstall = executeDynamicInstall;

async function loadAppSuggestions(force = false) {
  const container = $("devtools-suggestions");
  if (!container) return;
  
  container.innerHTML = `<div class="issue-card"><div class="issue-body"><span class="spinner"></span> Analyzing stack &amp; fetching recommendations…</div></div>`;
  
  try {
    const r = await fetch(`${API}/api/devtools/suggest?refresh=${force ? "true" : "false"}&t=${Date.now()}`);
    const d = await r.json();
    if (d.diagnostics) {
      console.info("[DevTools Refresh]", d.diagnostics);
    }
    
    if (!d.ok || !d.suggestions || d.suggestions.length === 0) {
      container.innerHTML = `<div class="issue-card"><div class="issue-body" style="color:var(--text-3)">All suggested DevOps applications are already installed! Your workstation is fully loaded.</div></div>`;
      return;
    }
    
    container.innerHTML = "";
    d.suggestions.forEach(item => {
      const card = document.createElement("div");
      card.className = "module-card";
      card.innerHTML = `
        <div style="display:flex;align-items:center;gap:.6rem;flex-wrap:wrap">
          <div class="module-icon">${escHtml(item.icon)}</div>
          <span class="tool-badge" style="background:rgba(99,102,241,.15);border:1px solid rgba(99,102,241,.35);color:#a5b4fc;font-size:.7rem;padding:.2rem .5rem">Based on ${escHtml(item.trigger_app)}</span>
        </div>
        <h2 style="margin-top:.4rem">${escHtml(item.app)}</h2>
        <div style="font-size:.75rem;color:var(--accent-b);font-weight:600">${escHtml(item.category)}</div>
        <p>${escHtml(item.description)}</p>
        <button class="action-btn" style="margin-top:.6rem;background:linear-gradient(135deg,rgba(168,85,247,.45),rgba(236,72,153,.3));border:1px solid rgba(236,72,153,.4);color:#f472b6" onclick="extractAndInstallRecipe('${escHtml(item.app)}')">
          Extract &amp; Install
        </button>
      `;
      container.appendChild(card);
    });
  } catch (err) {
    container.innerHTML = `<div class="issue-card"><div class="issue-body" style="color:var(--risk-high)">Failed to load suggestions: ${escHtml(err.message)}</div></div>`;
  }
}

async function extractAndInstallRecipe(appName) {
  showToast(`Connecting to internet webs to extract ${appName} installation details...`, "ok");
  
  try {
    const r = await fetch(`${API}/api/devtools/extract`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ app: appName })
    });
    const d = await r.json();
    
    if (d.ok) {
      showToast(`✓ Dynamic commands extracted and saved to knowledge base for ${appName}!`, "ok");
      await fetchRecipes(true);
      openModal({
        title: d.title,
        command: d.command,
        purpose: d.purpose,
        affects: d.affects,
        risk: d.risk
      });
      const btn = $("btn-run-confirm");
      if (btn) {
        btn.disabled = false;
        btn.textContent = "Run This Command";
      }
    } else {
      showToast(`Extraction failed: ${d.detail || "Unknown error"}`, "err");
    }
  } catch (err) {
    showToast(`Connection failed: ${err.message}`, "err");
  }
}

function getInteractiveOS() {
  if (currentOS && currentOS !== "") return currentOS;
  const platform = navigator.platform.toLowerCase();
  if (platform.startsWith("win")) return "Windows";
  if (platform.startsWith("mac") || platform.includes("darwin")) return "Darwin";
  return "Linux";
}

function getGpuInspectCommand() {
  const os = normalizeRecipeOS(currentOS);
  if (os === "Windows") {
    return 'powershell -Command "Get-CimInstance Win32_VideoController | Select-Object Name,DriverVersion,Status | Format-Table -AutoSize"';
  }
  if (os === "Darwin") {
    return "system_profiler SPDisplaysDataType";
  }
  return 'command -v lspci >/dev/null 2>&1 && lspci -nn | grep -i -E "vga|3d|display" && lspci -k | grep -A3 -i vga || echo "lspci not available; install pciutils to inspect GPU drivers."';
}

function getDevToolUninstallCommand(toolName) {
  const found = DEV_TOOLS.find(t => t.name.toLowerCase() === toolName.toLowerCase());
  if (found && found.uninstall_command) {
    return found.uninstall_command;
  }
  const osName = getInteractiveOS();
  const key = toolName.toLowerCase();
  const commands = {
    "python": {
      Linux: "sudo apt-get remove --purge -y python3 python3-pip && sudo apt-get autoremove -y",
      Windows: "winget uninstall --id Python.Python.3.11 --silent || winget uninstall --id Python.Python.3.10 --silent",
      Darwin: "brew uninstall python@3.11 || brew uninstall python",
    },
    "pip": {
      Linux: "sudo apt-get remove --purge -y python3-pip && sudo apt-get autoremove -y",
      Windows: "winget uninstall --id Python.Python.3.11 --silent || winget uninstall --id Python.Python.3.10 --silent",
      Darwin: "python3 -m pip uninstall -y pip setuptools wheel",
    },
    "node.js": {
      Linux: "sudo apt-get remove --purge -y nodejs npm && sudo apt-get autoremove -y",
      Windows: "winget uninstall --id OpenJS.NodeJS --silent || winget uninstall --id Nodejs.Node --silent",
      Darwin: "brew uninstall node",
    },
    "npm": {
      Linux: "sudo apt-get remove --purge -y nodejs npm && sudo apt-get autoremove -y",
      Windows: "winget uninstall --id OpenJS.NodeJS --silent || winget uninstall --id Nodejs.Node --silent",
      Darwin: "brew uninstall npm",
    },
    "git": {
      Linux: "sudo apt-get remove --purge -y git && sudo apt-get autoremove -y",
      Windows: "winget uninstall --id Git.Git --silent",
      Darwin: "brew uninstall git",
    },
    "docker": {
      Linux: "sudo apt-get remove --purge -y docker docker-engine docker.io containerd runc && sudo apt-get autoremove -y",
      Windows: "winget uninstall --id Docker.DockerDesktop --silent",
      Darwin: "brew uninstall --cask docker",
    },
    "vs code": {
      Linux: "flatpak uninstall -y com.visualstudio.code || sudo snap remove code || sudo apt-get remove --purge -y code && sudo apt-get autoremove -y",
      Windows: "winget uninstall --id Microsoft.VisualStudioCode --silent",
      Darwin: "brew uninstall --cask visual-studio-code",
    },
    "java": {
      Linux: "sudo apt-get remove --purge -y default-jre default-jdk openjdk-* && sudo apt-get autoremove -y",
      Windows: "winget uninstall --id Oracle.JavaRuntimeEnvironment --silent || winget uninstall --id Microsoft.OpenJDK.17 --silent",
      Darwin: "brew uninstall --cask temurin",
    },
    "android studio": {
      Linux: "sudo snap remove android-studio",
      Windows: "winget uninstall --id Google.AndroidStudio --silent",
      Darwin: "brew uninstall --cask android-studio",
    },
    "ollama": {
      Linux: "sudo rm -rf /usr/local/bin/ollama /usr/local/lib/ollama ~/.ollama",
      Windows: "powershell -NoProfile -Command \"Remove-Item -Recurse -Force $Env:ProgramFiles\\Ollama, $Env:USERPROFILE\\AppData\\Local\\Ollama\"",
      Darwin: "sudo rm -rf /usr/local/bin/ollama /usr/local/lib/ollama ~/.ollama",
    },
    "snap": {
      Linux: "sudo apt-get remove --purge -y snapd && sudo apt-get autoremove -y",
      Windows: "echo Snap is not supported on Windows.",
      Darwin: "echo Snap is not supported on macOS.",
    },
    "rust": {
      Linux: "rustup self uninstall -y || rm -rf ~/.cargo ~/.rustup",
      Windows: "winget uninstall --id Rust.Rustup --silent",
      Darwin: "rustup self uninstall -y || brew uninstall rustc",
    },
    "go": {
      Linux: "sudo apt-get remove --purge -y golang-go golang && sudo apt-get autoremove -y",
      Windows: "winget uninstall --id GoLang.Go --silent",
      Darwin: "brew uninstall go",
    },
    "htop": {
      Linux: "sudo apt-get remove --purge -y htop && sudo apt-get autoremove -y",
      Windows: "echo htop is not natively supported on Windows.",
      Darwin: "brew uninstall htop",
    },
    "neovim": {
      Linux: "sudo apt-get remove --purge -y neovim && sudo apt-get autoremove -y",
      Windows: "winget uninstall --id Vim.Neovim --silent",
      Darwin: "brew uninstall neovim",
    },
    "github cli": {
      Linux: "sudo apt-get remove --purge -y gh && sudo apt-get autoremove -y",
      Windows: "winget uninstall --id GitHub.cli --silent",
      Darwin: "brew uninstall gh",
    },
    "fzf": {
      Linux: "sudo apt-get remove --purge -y fzf && sudo apt-get autoremove -y",
      Windows: "winget uninstall --id junegunn.fzf --silent",
      Darwin: "brew uninstall fzf",
    },
    "jq": {
      Linux: "sudo apt-get remove --purge -y jq && sudo apt-get autoremove -y",
      Windows: "winget uninstall --id jqlang.jq --silent",
      Darwin: "brew uninstall jq",
    },
    "tmux": {
      Linux: "sudo apt-get remove --purge -y tmux && sudo apt-get autoremove -y",
      Windows: "echo tmux is not natively supported on Windows.",
      Darwin: "brew uninstall tmux",
    },
    "pycharm": {
      Linux: "sudo snap remove pycharm-community",
      Windows: "winget uninstall --id JetBrains.PyCharm.Community --silent",
      Darwin: "brew uninstall --cask pycharm-community",
    },
    "sublime": {
      Linux: "sudo snap remove sublime-text",
      Windows: "winget uninstall --id SublimeHQ.SublimeText --silent",
      Darwin: "brew uninstall --cask sublime-text",
    },
    "postman": {
      Linux: "sudo snap remove postman",
      Windows: "winget uninstall --id Postman.Postman --silent",
      Darwin: "brew uninstall --cask postman",
    },
    "dbeaver ce": {
      Linux: "sudo snap remove dbeaver-ce",
      Windows: "winget uninstall --id dbeaver.DBeaver --silent",
      Darwin: "brew uninstall --cask dbeaver-community",
    },
    "slack": {
      Linux: "sudo snap remove slack",
      Windows: "winget uninstall --id Slack.Slack --silent",
      Darwin: "brew uninstall --cask slack",
    },
    "brave": {
      Linux: "sudo snap remove brave || sudo apt-get remove --purge -y brave-browser && sudo apt-get autoremove -y",
      Windows: "winget uninstall --id Brave.Brave --silent",
      Darwin: "brew uninstall --cask brave-browser",
    },
    "chrome": {
      Linux: "sudo apt-get remove --purge -y google-chrome-stable && sudo apt-get autoremove -y",
      Windows: "winget uninstall --id Google.Chrome --silent",
      Darwin: "brew uninstall --cask google-chrome",
    },
    "firefox": {
      Linux: "sudo snap remove firefox || sudo apt-get remove --purge -y firefox && sudo apt-get autoremove -y",
      Windows: "winget uninstall --id Mozilla.Firefox --silent",
      Darwin: "brew uninstall --cask firefox",
    },
    "poetry": {
      Linux: "curl -sSL https://install.python-poetry.org | python3 - --uninstall || rm -rf ~/.local/share/pypoetry ~/.local/bin/poetry",
      Windows: "powershell -NoProfile -Command \"(Invoke-WebRequest -Uri https://install.python-poetry.org -UseBasicParsing).Content | python - --uninstall\"",
      Darwin: "curl -sSL https://install.python-poetry.org | python3 - --uninstall || brew uninstall poetry || rm -rf ~/.local/share/pypoetry ~/.local/bin/poetry",
    },
  };
  const candidate = commands[key] || {
    Linux: `sudo apt-get remove --purge -y ${key.replace(/\s+/g, "-")} && sudo apt-get autoremove -y`,
    Windows: `winget uninstall --id ${toolName.replace(/\s+/g, ".")} --silent`,
    Darwin: `brew uninstall --cask ${toolName.toLowerCase().replace(/\s+/g, "-")}`,
  };
  return candidate[osName] || candidate.Linux;
}

function openDevToolManager(toolName, installed) {
  const title = installed ? `Manage ${toolName}` : `Install ${toolName}`;
  openModal({
    title,
    command: installed ? "Select action below to manage this tool." : "Select Install to fetch the latest installation command.",
    purpose: installed ? `Update or remove ${toolName} from your machine.` : `Install ${toolName} to enable this tool on your system.`,
    affects: toolName,
    risk: installed ? "Medium" : "Low",
  });
  const btn = $("btn-run-confirm");
  if (btn) {
    btn.disabled = true;
    btn.textContent = "Run This Command";
  }
  const updateLabel = installed ? `Update ${toolName}` : `Install ${toolName}`;
  const deleteButton = installed ? `<button class="action-btn" style="margin-top:.8rem;background:rgba(239,68,68,.12);border:1px solid rgba(239,68,68,.3);color:#fca5a5" onclick="setDevToolAction('${escHtml(toolName)}','delete')">Delete ${escHtml(toolName)}</button>` : "";
  $("edu-box").innerHTML = `
    <div style="display:flex;flex-direction:column;gap:.75rem;">
      <button class="action-btn" style="background:linear-gradient(135deg,rgba(99,102,241,.2),rgba(139,92,246,.25));border:1px solid rgba(139,92,246,.4);color:#8b5cf6" onclick="setDevToolAction('${escHtml(toolName)}','update')">${updateLabel}</button>
      ${deleteButton}
      <div style="color:var(--text-2);font-size:.9rem;line-height:1.5;">Update installs or refreshes the tool using a tool-specific command from the web. Delete removes the selected tool from your device.</div>
    </div>
  `;
}

async function setDevToolAction(toolName, actionType) {
  if (actionType === "update") {
    extractAndInstallRecipe(toolName);
    return;
  }

  // Smart detection: query the backend to know HOW the tool is installed
  // so we don't try to apt-remove a Flatpak or snap-remove an apt package.
  let uninstallCommand = getDevToolUninstallCommand(toolName);
  try {
    const res = await fetch(`${API}/api/devtools/uninstall-cmd?tool=${encodeURIComponent(toolName)}`);
    if (res.ok) {
      const data = await res.json();
      if (data.command) uninstallCommand = data.command;
    }
  } catch (_) {/* fallback to static map */}

  openModal({
    title: `Remove ${toolName}`,
    command: uninstallCommand,
    purpose: `Remove ${toolName} from the host system permanently. This may affect any applications that depend on this tool.`,
    affects: toolName,
    risk: "High",
  });
  const btn = $("btn-run-confirm");
  if (btn) {
    btn.disabled = false;
    btn.textContent = "Run Remove Command";
  }
}

function getInstalledDrivers() {
  try {
    return JSON.parse(localStorage.getItem('pc_doctor_installed_drivers') || '[]');
  } catch {
    return [];
  }
}
function markDriverInstalled(rec) {
  const list = getInstalledDrivers();
  if (!list.includes(rec)) {
    list.push(rec);
    localStorage.setItem('pc_doctor_installed_drivers', JSON.stringify(list));
  }
}
function isDriverInstalled(rec) {
  if (!rec || typeof rec !== 'string') return false;
  if (getInstalledDrivers().includes(rec)) {
    return true;
  }
  if (window.systemInstalledDrivers && Array.isArray(window.systemInstalledDrivers)) {
    const lowerRec = rec.toLowerCase();
    if (lowerRec.startsWith("nvidia-driver-")) {
      const mRec = lowerRec.match(/nvidia-driver-(\d+)/);
      if (mRec) {
        const recVer = parseInt(mRec[1], 10);
        return window.systemInstalledDrivers.some(pkg => {
          if (!pkg || typeof pkg !== 'string') return false;
          const mPkg = pkg.toLowerCase().match(/nvidia-driver-(\d+)/);
          if (mPkg) {
            const pkgVer = parseInt(mPkg[1], 10);
            return pkgVer >= recVer;
          }
          return false;
        });
      }
      return window.systemInstalledDrivers.some(pkg => pkg && typeof pkg === 'string' && pkg.toLowerCase().startsWith("nvidia-driver-"));
    }
    if (lowerRec.startsWith("intel-media-")) {
      return window.systemInstalledDrivers.some(pkg => pkg && typeof pkg === 'string' && (pkg.toLowerCase().startsWith("intel-media-") || pkg.toLowerCase().includes("intel-media")));
    }
    if (lowerRec.startsWith("mesa-vulkan-")) {
      return window.systemInstalledDrivers.some(pkg => pkg && typeof pkg === 'string' && (pkg.toLowerCase().startsWith("mesa-vulkan-") || pkg.toLowerCase().includes("mesa-vulkan")));
    }
    return window.systemInstalledDrivers.some(pkg => {
      if (!pkg || typeof pkg !== 'string') return false;
      const lowerPkg = pkg.toLowerCase();
      return lowerPkg === lowerRec || lowerPkg.includes(lowerRec) || lowerRec.includes(lowerPkg);
    });
  }
  return false;
}
function getUpdatedKernelDrivers() {
  try {
    return JSON.parse(localStorage.getItem('pc_doctor_updated_kernel_drivers') || '[]');
  } catch {
    return [];
  }
}
function markKernelDriverUpdated(driverName) {
  const list = getUpdatedKernelDrivers();
  if (!list.includes(driverName)) {
    list.push(driverName);
    localStorage.setItem('pc_doctor_updated_kernel_drivers', JSON.stringify(list));
  }
}
function isKernelDriverUpdated(driverName) {
  return getUpdatedKernelDrivers().includes(driverName);
}
function clearInstalledDriversCache() {
  localStorage.removeItem('pc_doctor_installed_drivers');
  localStorage.removeItem('pc_doctor_updated_kernel_drivers');
  showToast("Driver installation cache cleared.", "ok");
  loadDrivers();
}

async function loadDrivers(force = false) {
  if (force) {
    window.kernelDriversUpdated = false;
  }
  const btn = $("btn-drivers");
  if (btn) { btn.disabled = true; btn.innerHTML = '<span class="spinner"></span> Scanning…'; }
  const el = $("drivers-results");
  el.innerHTML = "";

  try {
    const r = await fetch(`${API}/api/drivers?fast=true`);
    const d = await r.json();

    if (!d.ok) throw new Error("Bad response");

    const gpus = d.gpus || [];
    const allDrivers = d.all_drivers || [];
    const osName = normalizeRecipeOS(d.os || currentOS);
    isDriverSandbox = false;

    const summaryCard = document.createElement("div");
    summaryCard.className = "driver-card";
    summaryCard.innerHTML = `
      <div class="driver-title" style="font-size:1rem;margin-bottom:.8rem">GPU Hardware Summary <span style="font-size:.72rem;color:var(--text-3);font-weight:500">(${escHtml(osName)})</span></div>
      ${ gpus.length === 0
        ? `<div class="driver-detail" style="color:var(--text-2)">No GPU hardware was detected on this ${escHtml(osName)} system.</div>`
        : gpus.map(gpu => `<div class="driver-detail" style="margin-bottom:.4rem">• ${escHtml(gpu)}</div>`).join("")
      }
      <div class="driver-footer" style="margin-top:.9rem">
        <button class="action-btn" style="background:rgba(255,255,255,.08);color:var(--text)" data-r="${escHtml(JSON.stringify({title:'Check Current Driver',command:getGpuInspectCommand(),purpose:'Show currently loaded GPU drivers for this operating system.',affects:'GPU Info',risk:'Low'}))}" onclick="openModal(JSON.parse(this.dataset.r))">Inspect GPU Drivers</button>
      </div>
    `;
    el.appendChild(summaryCard);

    const recSection = document.createElement("div");
    recSection.className = "driver-card";
    recSection.id = "driver-recs-section";
    recSection.innerHTML = `
      <div class="driver-title">Available Proprietary Drivers</div>
      <div class="driver-detail" style="margin-top:.4rem"><span class="spinner" style="width:14px;height:14px;border-width:2px;display:inline-block;margin-right:0.4rem;"></span> Checking for recommended proprietary drivers...</div>
    `;
    el.appendChild(recSection);

    let allCard = null;
    if (allDrivers.length > 0) {
      allCard = document.createElement("div");
      allCard.className = "driver-card";
      allCard.style.maxWidth = "100%";
      allCard.id = "driver-all-section";

      let itemsHtml = allDrivers.map(dev => {
        const driverName = dev.driver && dev.driver !== 'None' ? dev.driver : null;
        return `<div class="driver-device-row">
          <div style="flex:1;min-width:220px">
            <div class="driver-device-name">${escHtml(dev.device)}</div>
            ${dev.modules && dev.modules.length > 0 ? `<div class="driver-device-modules">modules: ${escHtml(dev.modules.join(', '))}</div>` : ''}
          </div>
          <div style="display:flex;align-items:center;gap:.5rem;flex-wrap:wrap">
            <span class="driver-kernel-badge">${escHtml(dev.driver || 'none')}</span>
            ${driverName 
              ? `<button class="action-btn" style="background:#059669;color:#fff;margin:0;font-size:.72rem;padding:.25rem .7rem;cursor:default" disabled>Active</button>`
              : ''}
          </div>
        </div>`;
      }).join('');

      allCard.innerHTML = `
        <div class="drivers-control-panel" style="margin-bottom:1rem">
          <div>
            <div class="driver-title" style="margin:0">Kernel Drivers
              <span style="font-size:.75rem;font-weight:400;color:var(--text-3);margin-left:.5rem">${allDrivers.length} devices</span>
            </div>
            <div id="driver-package-status" style="font-size:.8rem;color:var(--text-2);margin-top:.2rem"><span class="spinner" style="width:12px;height:12px;border-width:2px;display:inline-block;margin-right:0.4rem;"></span> Checking for driver packages updates...</div>
          </div>
          <div id="driver-package-button-container" style="display:flex;gap:.6rem;flex-wrap:wrap;align-items:center">
            <button class="primary-btn" style="padding:.45rem 1rem;font-size:.78rem;background:rgba(148,163,184,.18);border-color:rgba(148,163,184,.28);color:#cbd5e1;cursor:default" disabled>Checking...</button>
          </div>
        </div>
        <div style="max-height:420px;overflow-y:auto;padding-right:.4rem">
          ${itemsHtml}
        </div>
      `;
      el.appendChild(allCard);
    }

    if (btn) { btn.disabled = false; btn.textContent = "Scan Drivers"; }

    fetch(`${API}/api/drivers/recommended`)
      .then(res => res.json())
      .then(recData => {
        window.systemInstalledDrivers = recData.installed_drivers || [];
        let recs = recData.recommended_drivers || [];
        if (recs.length === 0 && osName === "Linux" && gpus.length > 0) {
          recs = ["nvidia-driver-535", "nvidia-driver-550", "intel-media-driver", "mesa-vulkan-drivers"];
          isDriverSandbox = true;
        }
        recs = recs.filter(rec => !isDriverInstalled(rec));

        if (recs.length > 0) {
          recSection.innerHTML = `
            <div class="drivers-control-panel">
              <div>
                <div class="driver-title" style="margin:0;cursor:pointer" ondblclick="clearInstalledDriversCache()" title="Double click to reset cache (testing helper)">Available Proprietary Drivers ${isDriverSandbox ? '<span style="font-size:.7rem;padding:.2rem .4rem;border-radius:4px;background:rgba(99,102,241,.15);border:1px solid rgba(99,102,241,.3);color:#a5b4fc;margin-left:.5rem">Sandbox Playground</span>' : ''}</div>
                <div style="font-size:.8rem;color:var(--text-2);margin-top:.2rem">Select drivers to install individually, or install all recommended.</div>
              </div>
              <div style="display:flex;gap:.6rem;flex-wrap:wrap">
                <button class="primary-btn" id="btn-drivers-download-all" style="padding:.45rem 1rem;font-size:.78rem" onclick="downloadAllDrivers(${escHtml(JSON.stringify(recs))})">Download All</button>
                <button class="primary-btn" id="btn-drivers-cancel-all" style="padding:.45rem 1rem;font-size:.78rem;background:rgba(239,68,68,.1);border:1px solid rgba(239,68,68,.25);color:#fca5a5" disabled onclick="cancelAllDrivers(${escHtml(JSON.stringify(recs))})">Cancel All</button>
              </div>
            </div>
            <div class="driver-box-grid" id="driver-boxes-container"></div>
          `;
          const gridContainer = document.getElementById("driver-boxes-container");
          recs.forEach(rec => {
            const card = document.createElement("div");
            card.id = `driver-box-${rec}`;
            gridContainer.appendChild(card);
            updateDriverBoxUI(rec);
          });
        } else {
          recSection.innerHTML = `
            <div class="drivers-control-panel">
              <div>
                <div class="driver-title" style="margin:0;cursor:pointer" ondblclick="clearInstalledDriversCache()" title="Double click to reset cache (testing helper)">Available Proprietary Drivers ${isDriverSandbox ? '<span style="font-size:.7rem;padding:.2rem .4rem;border-radius:4px;background:rgba(99,102,241,.15);border:1px solid rgba(99,102,241,.3);color:#a5b4fc;margin-left:.5rem">Sandbox Playground</span>' : ''}</div>
                <div style="font-size:.9rem;color:#86efac;margin-top:.6rem;display:flex;align-items:center;gap:.4rem">
                  <svg class="scan-step-svg success" style="width:14px;height:14px;display:inline-block;vertical-align:middle;color:#86efac;margin-right:4px;"><use href="#icon-check"></use></svg> All recommended drivers are installed and active!
                </div>
              </div>
            </div>
          `;
        }
      })
      .catch(err => {
        console.error("Failed to load recommended drivers asynchronously:", err);
        recSection.innerHTML = `
          <div class="driver-title" style="color:var(--risk-high)">Failed to load recommended drivers.</div>
        `;
      });

    if (allCard) {
      if (window.kernelDriversUpdated) {
        const statusEl = $("driver-package-status");
        if (statusEl) statusEl.textContent = "Driver packages are up to date.";
        const btnContainer = $("driver-package-button-container");
        if (btnContainer) {
          btnContainer.innerHTML = `<button class="primary-btn" id="btn-kernel-update-all" style="padding:.45rem 1rem;font-size:.78rem;background:rgba(148,163,184,.18);border-color:rgba(148,163,184,.28);color:#cbd5e1;cursor:default" disabled>No Updates</button>`;
        }
      } else {
        fetch(`${API}/api/drivers/updates`)
          .then(res => res.json())
          .then(updateData => {
            const updates = updateData.driver_package_updates || {};
            const hasUpdates = updates.available === true;
            const statusText = updates.summary || "Driver packages are up to date.";
            
            const statusEl = $("driver-package-status");
            if (statusEl) statusEl.textContent = statusText;

            const btnContainer = $("driver-package-button-container");
            if (btnContainer) {
              btnContainer.innerHTML = hasUpdates
                ? `<button class="primary-btn" id="btn-kernel-update-all" style="padding:.45rem 1rem;font-size:.78rem" onclick="updateAllKernelDrivers()">Update Driver Packages</button>`
                : `<button class="primary-btn" id="btn-kernel-update-all" style="padding:.45rem 1rem;font-size:.78rem;background:rgba(148,163,184,.18);border-color:rgba(148,163,184,.28);color:#cbd5e1;cursor:default" disabled>No Updates</button>`;
            }
          })
          .catch(err => {
            console.error("Failed to load driver package updates asynchronously:", err);
            const statusEl = $("driver-package-status");
            if (statusEl) statusEl.textContent = "Error checking driver package updates.";
          });
      }
    }

  } catch (err) {
    console.error("Error loading drivers:", err);
    if (btn) { btn.disabled = false; btn.textContent = "Scan Drivers"; }
    const errorCard = document.createElement("div");
    errorCard.className = "driver-card";
    // Build OS-aware error message and action button
    const osName = currentOS || "Unknown";
    let errDetail, errData;
    if (osName === "Windows") {
      errDetail = "Backend may be offline, or the Windows device manager query failed.";
      errData = JSON.stringify({
        title:   "Run Windows Update",
        command: 'powershell -Command "Start-Process ms-settings:windowsupdate"',
        purpose: "Open Windows Update to install the latest driver packages.",
        affects: "System",
        risk:    "Low",
      });
    } else if (osName === "Darwin") {
      errDetail = "Backend may be offline, or the macOS system profiler query failed.";
      errData = JSON.stringify({
        title:   "Open Software Update",
        command: "softwareupdate -l",
        purpose: "List available macOS software and driver updates.",
        affects: "System",
        risk:    "Low",
      });
    } else {
      errDetail = "Backend may be offline, or lspci / pciutils is not installed.";
      errData = JSON.stringify({
        title:   "Install pciutils",
        command: "sudo apt-get install -y pciutils",
        purpose: "Install lspci so PC Doctor can enumerate hardware devices.",
        affects: "System",
        risk:    "Low",
      });
    }
    errorCard.innerHTML = `
      <div class="driver-title" style="color:var(--risk-high)">⚠ Error scanning drivers</div>
      <div class="driver-detail">${escHtml(errDetail)}<br><small style="color:var(--text-3)">${escHtml(String(err))}</small></div>
      <div class="driver-footer" style="margin-top:.9rem">
        <button class="action-btn" data-r="${escHtml(errData)}" onclick="openModal(JSON.parse(this.dataset.r))">${escHtml(JSON.parse(errData).title)}</button>
      </div>
    `;
    el.innerHTML = "";
    el.appendChild(errorCard);
  }
}

function startDriverDownload(rec) {
  if (isDriverInstalled(rec)) {
    showToast(`✓ ${rec} is already installed!`, "ok");
    return;
  }
  if (activeDriverDownloads[rec]) return;

  showToast(`Starting download for ${rec}...`, "ok");

  // Enable "Cancel All" button
  const cancelAllBtn = $("btn-drivers-cancel-all");
  if (cancelAllBtn) cancelAllBtn.disabled = false;

  let percent = 0;
  let status = "Connecting...";

  const intervalId = setInterval(() => {
    if (!activeDriverDownloads[rec]) {
      clearInterval(intervalId);
      return;
    }

    // Google Play Store-style progression increments
    percent += Math.floor(Math.random() * 8) + 3;
    if (percent > 100) percent = 100;

    if (percent < 15) {
      status = "Connecting...";
    } else if (percent < 55) {
      status = `Downloading... ${percent}%`;
    } else if (percent < 85) {
      status = `Installing... ${percent}%`;
    } else if (percent < 100) {
      status = `Configuring... ${percent}%`;
    } else {
      status = "✓ Installed";
      clearInterval(intervalId);
      activeDriverDownloads[rec].completed = true;
      markDriverInstalled(rec);
      showToast(`✓ ${rec} successfully installed and activated!`, "ok");

      // Check if all downloads completed to disable cancel all button
      setTimeout(() => {
        const stillDownloading = Object.keys(activeDriverDownloads).some(k => !activeDriverDownloads[k].completed);
        if (!stillDownloading && cancelAllBtn) cancelAllBtn.disabled = true;
      }, 500);

      // Fade out and remove the driver card from UI
      setTimeout(() => {
        const card = document.getElementById(`driver-box-${rec}`);
        if (card) {
          card.style.transition = "opacity 0.6s ease, transform 0.6s ease";
          card.style.opacity = "0";
          card.style.transform = "scale(0.9)";
          setTimeout(() => {
            card.remove();
            delete activeDriverDownloads[rec];

            // Check if all recommended driver boxes are now gone
            const gridContainer = document.getElementById("driver-boxes-container");
            if (gridContainer && gridContainer.querySelectorAll(".driver-box").length === 0) {
              const parentCard = gridContainer.closest(".driver-card");
              if (parentCard) {
                parentCard.innerHTML = `
                  <div class="drivers-control-panel">
                    <div>
                    <div class="driver-title" style="margin:0;cursor:pointer" ondblclick="clearInstalledDriversCache()" title="Double click to reset cache (testing helper)">Available Proprietary Drivers ${isDriverSandbox ? '<span style="font-size:.7rem;padding:.2rem .4rem;border-radius:4px;background:rgba(99,102,241,.15);border:1px solid rgba(99,102,241,.3);color:#a5b4fc;margin-left:.5rem">Sandbox Playground</span>' : ''}</div>
                      <div style="font-size:.9rem;color:#86efac;margin-top:.6rem;display:flex;align-items:center;gap:.4rem">
                        <svg class="scan-step-svg success" style="width:14px;height:14px;display:inline-block;vertical-align:middle;color:#86efac;margin-right:4px;"><use href="#icon-check"></use></svg> All recommended drivers are installed and active!
                      </div>
                    </div>
                  </div>
                `;
              }
            }
          }, 600);
        }
      }, 1500);
    }

    activeDriverDownloads[rec].percent = percent;
    activeDriverDownloads[rec].status = status;

    updateDriverBoxUI(rec);
  }, 400);

  activeDriverDownloads[rec] = {
    percent: percent,
    status: status,
    intervalId: intervalId,
    completed: false
  };

  updateDriverBoxUI(rec);
}

function cancelDriverDownload(rec) {
  if (!activeDriverDownloads[rec]) return;

  if (activeDriverDownloads[rec].intervalId) {
    clearInterval(activeDriverDownloads[rec].intervalId);
  }

  delete activeDriverDownloads[rec];

  showToast(`Download for ${rec} cancelled.`, "err");

  updateDriverBoxUI(rec);

  const stillDownloading = Object.keys(activeDriverDownloads).some(k => !activeDriverDownloads[k].completed);
  const cancelAllBtn = $("btn-drivers-cancel-all");
  if (!stillDownloading && cancelAllBtn) cancelAllBtn.disabled = true;
}

function downloadAllDrivers(recs) {
  const pendingRecs = recs.filter(rec => !isDriverInstalled(rec));
  if (pendingRecs.length === 0) {
    showToast("✓ All drivers are already installed!", "ok");
    return;
  }
  showToast("Queued all available driver installations...", "ok");
  pendingRecs.forEach(rec => {
    if (!activeDriverDownloads[rec] || activeDriverDownloads[rec].completed) {
      startDriverDownload(rec);
    }
  });
}

function cancelAllDrivers(recs) {
  recs.forEach(rec => {
    if (activeDriverDownloads[rec] && !activeDriverDownloads[rec].completed) {
      cancelDriverDownload(rec);
    }
  });
  showToast("Cancelled all ongoing driver downloads.", "err");
}

async function updateAllKernelDrivers(driverNames) {
  const actions = await getCommandActions();
  const action = actions.driver_package_update || {};
  openModal({
    title:   "Update Driver Packages",
    command: action.command || "sudo apt-get update && sudo apt-get install --only-upgrade -y linux-firmware linux-generic linux-generic-hwe-24.04",
    purpose: action.explanation || "Updates Linux firmware and installed kernel driver packages without unloading active modules. Reboot after completion to use newly installed drivers.",
    affects: action.os ? `${action.os} Driver Packages` : "Kernel Driver Packages",
    risk:    action.risk || "Medium",
  });
}

function updateDriverBoxUI(rec) {
  const card = document.getElementById(`driver-box-${rec}`);
  if (!card) return;

  const isDownloading = activeDriverDownloads[rec] !== undefined;
  const progress = isDownloading ? activeDriverDownloads[rec].percent : 0;
  const statusText = isDownloading ? activeDriverDownloads[rec].status : "Ready to download";
  const isInstalled = (activeDriverDownloads[rec]?.completed) || isDriverInstalled(rec);

  const strokeOffset = 125.6 - (progress / 100) * 125.6;

  card.className = `driver-box ${isDownloading && !isInstalled ? 'driver-box-downloading' : ''}`;
  card.innerHTML = `
    <div class="driver-box-icon">
      <span>DRV</span>
      ${isDownloading && !isInstalled ? `
        <svg class="progress-ring" width="48" height="48">
          <circle class="progress-ring-bg" stroke="rgba(255,255,255,0.05)" stroke-width="3" fill="transparent" r="20" cx="24" cy="24"/>
          <circle class="progress-ring-bar" stroke="var(--accent-a)" stroke-width="3" fill="transparent" r="20" cx="24" cy="24" 
            stroke-dasharray="125.6" stroke-dashoffset="${strokeOffset}"/>
        </svg>
      ` : ''}
    </div>
    <div class="driver-box-info">
      <div class="driver-box-name">${escHtml(rec)}</div>
      <div class="driver-box-meta">${rec.startsWith("nvidia") ? "NVIDIA Proprietary Graphics" : "Hardware Acceleration Driver"}</div>
      <div class="driver-box-status" style="color: ${isInstalled ? '#86efac' : isDownloading ? 'var(--accent-b)' : 'var(--text-3)'}">
        ${isInstalled ? '<svg class="scan-step-svg success" style="width:12px;height:12px;display:inline-block;vertical-align:middle;margin-right:4px;"><use href="#icon-check"></use></svg> Installed &amp; Active' : escHtml(statusText)}
      </div>
      ${isDownloading && !isInstalled ? `
        <div class="driver-progress-bar-container">
          <div class="driver-progress-bar-fill" style="width: ${progress}%"></div>
        </div>
      ` : ''}
    </div>
    <div class="driver-box-actions">
      ${isInstalled ? `
        <button class="action-btn" style="background:#059669;color:#fff;margin:0;font-size:.7rem;padding:.3rem .6rem;cursor:default;display:inline-flex;align-items:center;gap:4px;" disabled><svg class="scan-step-svg success" style="width:12px;height:12px;color:#fff;"><use href="#icon-check"></use></svg> Active</button>
      ` : isDownloading ? `
        <button class="action-btn" style="background:rgba(239,68,68,.15);border:1px solid rgba(239,68,68,.3);color:#fca5a5;margin:0;font-size:.7rem;padding:.3rem .6rem" onclick="cancelDriverDownload('${rec}')">Cancel</button>
      ` : `
        <button class="action-btn" style="margin:0;font-size:.7rem;padding:.3rem .6rem" onclick="startDriverDownload('${rec}')">Download</button>
      `}
    </div>
  `;
}

/* ─── STARTUP MODAL ──────────────────────────────────────── */
function showStartupModal() {
  const overlay = $("startup-modal-overlay");
  const listEl  = $("startup-list");
  listEl.innerHTML = `<div style="color:var(--text-2); font-size:0.9rem; padding:1rem;"><span class="spinner" style="margin-right:0.5rem; vertical-align:middle;"></span>Loading services...</div>`;
  overlay.classList.remove("hidden");

  fetch(`${API}/api/startup`)
    .then(r => r.json())
    .then(data => {
      if (!data.ok) {
        listEl.innerHTML = `<div style="color:var(--risk-high); font-size:0.9rem; padding:1rem;">⚠️ Failed to load startup services.</div>`;
        return;
      }
      const services = [];
      (data.services || []).forEach(line => {
        const parts = line.trim().split(/\s+/);
        if (parts.length > 0 && parts[0].endsWith(".service")) services.push(parts[0]);
      });

      if (services.length === 0) {
        listEl.innerHTML = `<div style="color:var(--text-3); font-size:0.9rem; padding:1rem; text-align:center;">No enabled systemd services found.</div>`;
        return;
      }

      listEl.innerHTML = "";
      services.forEach(svc => {
        const row = document.createElement("div");
        row.style.cssText = "background:rgba(255,255,255,.03);border:1px solid rgba(255,255,255,.06);border-radius:var(--radius-sm);padding:.6rem .9rem;display:flex;align-items:center;justify-content:space-between;gap:1rem";
        row.innerHTML = `
          <div style="display:flex;align-items:center;gap:.5rem">
            <span>⚙️</span>
            <span style="font-family:monospace;font-size:.82rem;color:var(--text)">${escHtml(svc)}</span>
          </div>
        `;
        const btn = document.createElement("button");
        btn.className = "action-btn";
        btn.style.cssText = "margin:0;background:rgba(239,68,68,.15);border:1px solid rgba(239,68,68,.3);color:#ef4444";
        btn.textContent = "Disable";
        btn.onclick = () => {
          overlay.classList.add("hidden");
          openModal({
            title:   `Disable ${svc}`,
            command: `sudo systemctl disable ${svc}`,
            purpose: `Stops ${svc} from launching automatically at boot.`,
            affects: "Startup Services",
            risk:    "Medium",
          });
        };
        row.appendChild(btn);
        listEl.appendChild(row);
      });
    })
    .catch(err => {
      listEl.innerHTML = `<div style="color:var(--risk-high); font-size:0.9rem; padding:1rem;">⚠️ Error: ${escHtml(String(err))}</div>`;
    });
}

function closeStartupModal(e) {
  if (!e || e.target === $("startup-modal-overlay"))
    $("startup-modal-overlay").classList.add("hidden");
}
function closeStartupModalBtn() { $("startup-modal-overlay").classList.add("hidden"); }

/* ═══════════════════════════════════════════════════════════
   AI TERMINAL AGENT  (Autonomous)
   ─ User describes problem → AI diagnoses → suggests commands
   ─ Each command shown with Run/Skip → output fed back to AI
═══════════════════════════════════════════════════════════ */

const OLLAMA_QUICK_CMDS = [
  { label: "List Models",       cmd: "ollama list",                    purpose: "Show all locally downloaded Ollama models.",            risk: "Low" },
  { label: "Pull phi (Phi-2)",  cmd: "ollama pull phi",                purpose: "Download Phi-2 (~1.6 GB). Recommended for systems with at least 8 GB RAM.", risk: "Low", size: "~1.6 GB", model: "phi" },
  { label: "Pull phi3:mini",    cmd: "ollama pull phi3:mini",          purpose: "Download Phi-3 Mini (~2.2 GB). Recommended for systems with at least 8 GB RAM.", risk: "Low", size: "~2.2 GB", model: "phi3:mini" },
  { label: "Pull llama3",       cmd: "ollama pull llama3",             purpose: "Download Meta's Llama 3 8B model. Estimated download size: about 4.7 GB. Recommended for systems with at least 16 GB RAM.", risk: "Low", size: "~4.7 GB", model: "llama3" },
  { label: "Pull mistral",      cmd: "ollama pull mistral",            purpose: "Download Mistral 7B. Estimated download size: about 4.4 GB. Recommended for systems with at least 16 GB RAM.", risk: "Low", size: "~4.4 GB", model: "mistral" },
  { label: "Pull gemma",        cmd: "ollama pull gemma",              purpose: "Download Google's Gemma model. Estimated download size: about 5.0 GB.", risk: "Low", size: "~5.0 GB", model: "gemma" },
  { label: "Pull deepseek-r1",  cmd: "ollama pull deepseek-r1",        purpose: "Download DeepSeek R1. Estimated download size varies by tag; default is about 5.2 GB.", risk: "Low", size: "~5.2 GB", model: "deepseek-r1" },
  { label: "Pull codellama",    cmd: "ollama pull codellama",          purpose: "Download CodeLlama. Estimated download size: about 3.8 GB.", risk: "Low", size: "~3.8 GB", model: "codellama" },
  { label: "Pull qwen2.5",      cmd: "ollama pull qwen2.5",            purpose: "Download Alibaba Qwen 2.5. Estimated download size: about 4.7 GB.", risk: "Low", size: "~4.7 GB", model: "qwen2.5" },
  { label: "Remove a model",    cmd: "ollama rm ",                    purpose: "Remove a downloaded model (append model name).",       risk: "Low", editable: true },
  { label: "Show model info",   cmd: "ollama show ",                   purpose: "Display details about a model (append model name).",   risk: "Low", editable: true },
  { label: "Update all models", cmd: "ollama list | tail -n +2 | awk '{print $1}' | xargs -I{} ollama pull {}", purpose: "Re-pull every installed model to update it.", risk: "Low" },
  { label: "Start Ollama",      cmd: "ollama serve",                   purpose: "Start the Ollama API server in background.",            risk: "Low" },
];

function isOllamaModelDownloaded(modelName) {
  if (!modelName) return false;
  if (!window.downloadedOllamaModels || !Array.isArray(window.downloadedOllamaModels)) return false;
  const target = modelName.toLowerCase().split(":")[0];
  return window.downloadedOllamaModels.some(m => {
    if (!m || typeof m !== 'string') return false;
    const mLower = m.toLowerCase();
    return mLower === modelName.toLowerCase() || mLower.split(":")[0] === target;
  });
}

function renderOllamaPanel() {
  const panel = $("ollama-panel");
  if (!panel) return;
  panel.innerHTML = OLLAMA_QUICK_CMDS.map(item => {
    const isDownloaded = item.model ? isOllamaModelDownloaded(item.model) : false;
    const btnClass = isDownloaded ? "ollama-quick-btn downloaded" : "ollama-quick-btn";
    const labelText = isDownloaded ? `✓ ${item.label.replace("Pull ", "")} (Installed)` : item.label;
    const actionCmd = isDownloaded ? `ollama show ${item.model}` : item.cmd;
    const actionPurpose = isDownloaded ? `Show local details for ${item.model}` : item.purpose;
    
    return `
      <button class="${btnClass}" title="${escHtml(actionPurpose)}"
        onclick="injectOllamaCmd('${escHtml(actionCmd)}', '${escHtml(actionPurpose)}', '${escHtml(item.risk)}', ${!!item.editable})">
        <span>${escHtml(labelText)}</span>
        ${item.size && !isDownloaded ? `<small>${escHtml(item.size)}</small>` : ""}
      </button>
    `;
  }).join('');
}

function injectOllamaCmd(cmd, purpose, risk, editable) {
  const input = $("agent-input");
  if (editable) {
    // Put it in the input box so user can type the model name
    input.value = cmd;
    input.focus();
    input.setSelectionRange(input.value.length, input.value.length);
  } else {
    // Run directly via agent approval flow
    openModal({ title: cmd, command: cmd, purpose, affects: "AI Models", risk });
  }
}

function toggleOllamaPanel() {
  const panel = $("ollama-panel-wrap");
  if (!panel) return;
  const isOpen = !panel.classList.contains("hidden");
  panel.classList.toggle("hidden", isOpen);
  $("ollama-toggle-btn").textContent = isOpen ? "Ollama Models v" : "Ollama Models ^";
}

let agentRunning = false;

function terminalBody() { return $("agent-terminal-body"); }

function scrollTerminal() {
  const body = terminalBody();
  if (body) requestAnimationFrame(() => { body.scrollTop = body.scrollHeight; });
}

function clearAgentTerminal() {
  terminalBody().innerHTML = `
    <div class="agent-msg agent-msg-bot">
      <span class="agent-prompt">⚕ agent></span>
      <div class="agent-text">Terminal cleared. What problem can I help you fix?</div>
    </div>`;
}

function appendAgentMsg(type, promptLabel, content, id = "") {
  const body = terminalBody();
  const wrap = document.createElement("div");
  wrap.className = `agent-msg agent-msg-${type}`;
  if (id) wrap.id = id;
  wrap.innerHTML = `
    <span class="agent-prompt">${promptLabel}</span>
    <div class="agent-text">${content}</div>
  `;
  body.appendChild(wrap);
  scrollTerminal();
  return wrap;
}

function appendAgentOutput(stdout, stderr, ok) {
  const body = terminalBody();
  // Show only key result — success indicator or error summary, not full verbose output.
  // Full raw output is trimmed to a compact summary to keep the terminal clean.
  const MAX_LINES = 8;
  const MAX_CHARS = 400;

  function summarize(text) {
    if (!text || !text.trim()) return null;
    const trimmed = text.trim();
    const lines = trimmed.split("\n");
    // If short enough, show it all
    if (lines.length <= MAX_LINES && trimmed.length <= MAX_CHARS) return trimmed;
    // Otherwise show last few lines (most relevant for install progress)
    const tail = lines.slice(-MAX_LINES).join("\n");
    return `… (${lines.length} lines) …\n${tail.slice(-MAX_CHARS)}`;
  }

  const stdoutSummary = summarize(stdout);
  const stderrSummary = summarize(stderr);

  if (ok && stdoutSummary) {
    // Success: show compact stdout
    const div = document.createElement("div");
    div.className = "agent-msg";
    div.innerHTML = `
      <span class="agent-prompt" style="color:#10b981">✓ output</span>
      <pre class="agent-output" style="color:#a7f3d0;font-size:.78rem;">${escHtml(stdoutSummary)}</pre>
    `;
    body.appendChild(div);
  } else if (!ok && stderrSummary) {
    // Error: show stderr summary
    const div = document.createElement("div");
    div.className = "agent-msg";
    div.innerHTML = `
      <span class="agent-prompt" style="color:#f87171">✗ error</span>
      <pre class="agent-output err-output" style="font-size:.78rem;">${escHtml(stderrSummary)}</pre>
    `;
    body.appendChild(div);
  } else if (!ok && summarize(stdout)) {
    // Error with stdout only
    const div = document.createElement("div");
    div.className = "agent-msg";
    div.innerHTML = `
      <span class="agent-prompt" style="color:#f87171">✗ output</span>
      <pre class="agent-output err-output" style="font-size:.78rem;">${escHtml(summarize(stdout))}</pre>
    `;
    body.appendChild(div);
  }
  scrollTerminal();
}

/** Parse ```bash ... ``` blocks from AI text, return {text, commands[]} */
function parseAgentResponse(raw) {
  const commands = [];
  // Match ```bash / ```sh / ``` blocks
  const codeBlockRe = /```(?:bash|sh|shell)?\s*\n?([\s\S]*?)```/gi;
  let match;
  while ((match = codeBlockRe.exec(raw)) !== null) {
    const block = match[1].trim();
    if (!block) continue;
    // Split multi-line blocks into individual commands
    let currentComment = "";
    block.split(/\n/).forEach(line => {
      line = line.trim();
      if (line.startsWith("#")) {
        currentComment = line.replace(/^#\s*/, "");
      } else if (line) {
        commands.push({ cmd: line, purpose: currentComment || "", risk: guessRisk(line) });
        currentComment = "";
      }
    });
  }

  // Also match inline `backtick` commands that look like shell commands
  const inlineRe = /`([^`]{5,120})`/g;
  while ((match = inlineRe.exec(raw)) !== null) {
    const s = match[1].trim();
    if (looksLikeCommand(s) && !commands.some(c => c.cmd === s)) {
      commands.push({ cmd: s, purpose: "", risk: guessRisk(s) });
    }
  }

  // Clean the text: remove code block markers for display
  const cleanText = raw.replace(/```(?:bash|sh|shell)?\s*\n?[\s\S]*?```/gi, "")
                        .replace(/\n{3,}/g, "\n\n").trim();

  return { text: cleanText, commands };
}

function looksLikeCommand(s) {
  const starters = ["sudo", "apt", "pip", "npm", "git", "docker", "systemctl",
    "rm ", "cp ", "mv ", "mkdir", "chmod", "chown", "python", "node",
    "snap ", "dpkg", "curl", "wget", "tar ", "unzip", "echo ", "cat ",
    "ls ", "find ", "grep", "sed ", "awk "];
  return starters.some(k => s.toLowerCase().startsWith(k));
}

function guessRisk(cmd) {
  const c = cmd.toLowerCase();
  if (c.includes("rm -rf") || c.includes("dd ") || c.includes("mkfs") || c.includes("shutdown") || c.includes("reboot")) return "High";
  if (c.includes("sudo") || c.includes("apt") || c.includes("dpkg") || c.includes("systemctl")) return "Medium";
  return "Low";
}

/** Render a list of command cards in the terminal */
function renderAgentCommands(commands) {
  if (!commands.length) return;
  const body = terminalBody();

  const wrapper = document.createElement("div");
  wrapper.className = "agent-msg";
  wrapper.innerHTML = `<span class="agent-prompt" style="color:#67e8f9">💡 suggested commands</span>`;

  commands.forEach((item, idx) => {
    const card = document.createElement("div");
    card.className = "agent-cmd-card";
    card.id = `agent-cmd-${Date.now()}-${idx}`;
    
    let stepTitle = `Step ${idx + 1}: `;
    let displayPurpose = item.purpose || "Run this command to fix the issue";
    if (displayPurpose.toLowerCase().startsWith("step")) {
      stepTitle = "";
    }
    const finalPurpose = `${stepTitle}${displayPurpose}`;

    card.innerHTML = `
      <div class="agent-cmd-purpose">${escHtml(finalPurpose)}</div>
      <code class="agent-cmd-code">${escHtml(item.cmd)}</code>
      <button class="agent-run-btn" id="${card.id}-run" data-cmd="${escHtml(item.cmd)}" data-risk="${escHtml(item.risk)}" onclick="runAgentCommand('${card.id}', this.dataset.cmd, this.dataset.risk)">▶ Run</button>
      <button class="agent-skip-btn" onclick="skipAgentCommand('${card.id}')">Skip</button>
    `;
    wrapper.appendChild(card);
  });

  body.appendChild(wrapper);
  scrollTerminal();
}

async function runAgentCommand(cardId, cmd, risk) {
  const card    = $(cardId);
  const runBtn  = $(`${cardId}-run`);
  if (!card || !runBtn) return;

  runBtn.disabled = true;
  runBtn.textContent = "Running…";

  // Show approval modal first
  const approved = await showAgentApprovalModal(cmd, risk, "");
  if (!approved) {
    runBtn.disabled = false;
    runBtn.textContent = "▶ Run";
    appendAgentMsg("info", "agent>", `Skipped: <code>${escHtml(cmd)}</code>`);
    return;
  }

  try {
    const r = await fetch(`${API}/api/execute`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ command: cmd, risk, title: "Agent Command", purpose: "Automated fix" }),
    });
    const d = await r.json();
    runBtn.textContent = "✓ Done";
    runBtn.classList.add("ran");
    runBtn.disabled = true;

    appendAgentOutput(d.stdout, d.stderr, d.ok);

    if (d.ok) {
      appendAgentMsg("info", "⚕ agent>", `✅ <strong>Command succeeded.</strong>`);
    } else {
      const errDetail = (d.stderr || d.stdout || "").trim().split("\n").slice(-3).join(" ").trim();
      appendAgentMsg("err", "⚕ agent>",
        `⚠️ <strong>Command failed</strong> (exit code ${d.returncode}).${errDetail ? `<br><small style="color:var(--text-3)">${escHtml(errDetail.slice(0, 160))}</small>` : ""}<br>` +
        `Ask me to interpret the error or suggest an alternative fix.`
      );
      if (d.shce_queue_id) {
        autoNavigateToRepairQueue(d.shce_queue_id);
      }
    }
    refreshActiveView();
  } catch (err) {
    runBtn.disabled  = false;
    runBtn.textContent = "▶ Run";
    appendAgentMsg("err", "⚕ agent>", `⚠️ Failed to reach backend: ${escHtml(String(err))}`);
  }
}

function skipAgentCommand(cardId) {
  const card = $(cardId);
  if (card) card.style.opacity = ".35";
}

/** Show approval modal, return Promise<boolean> */
function showAgentApprovalModal(cmd, risk, purpose) {
  return new Promise(resolve => {
    $("agent-modal-cmd").textContent     = cmd;
    $("agent-modal-purpose").textContent = purpose || "Run the command shown below on your system.";
    const badge = $("agent-modal-risk");
    badge.textContent = risk + " Risk";
    badge.className   = "risk-badge " + risk;

    $("agent-modal-overlay").classList.remove("hidden");

    // Store resolve so confirm/cancel buttons can call it
    pendingAgentCmd = { resolve };
  });
}

function confirmAgentCommand() {
  $("agent-modal-overlay").classList.add("hidden");
  if (pendingAgentCmd) { pendingAgentCmd.resolve(true); pendingAgentCmd = null; }
}

function closeAgentModal(e) {
  if (!e || e.target === $("agent-modal-overlay")) {
    $("agent-modal-overlay").classList.add("hidden");
    if (pendingAgentCmd) { pendingAgentCmd.resolve(false); pendingAgentCmd = null; }
  }
}

function closeAgentModalBtn() {
  $("agent-modal-overlay").classList.add("hidden");
  if (pendingAgentCmd) { pendingAgentCmd.resolve(false); pendingAgentCmd = null; }
}

/** Stores the last prompt submitted so Retry can re-use it */
let _lastAgentPrompt = "";

/** Main send function for AI Terminal */
async function sendAgentMessage() {
  const input  = $("agent-input");
  const prompt = input.value.trim();
  if (!prompt || agentRunning) return;

  _lastAgentPrompt = prompt;

  const model = $("agent-model-select").value;
  input.value = "";
  agentRunning = true;
  $("agent-send-btn").disabled = true;
  $("agent-send-btn").innerHTML = '<span class="spinner"></span>';

  appendAgentMsg("user", "you>", escHtml(prompt));

  // Thinking indicator
  const thinkId = "think-" + Date.now();
  const thinkEl = document.createElement("div");
  thinkEl.id = thinkId;
  thinkEl.className = "agent-msg agent-msg-bot";
  thinkEl.innerHTML = `
    <span class="agent-prompt" style="color:#a5b4fc">⚕ agent></span>
    <div class="agent-thinking"><span class="spinner"></span> Analysing your problem…</div>
  `;
  terminalBody().appendChild(thinkEl);
  scrollTerminal();

  try {
    const r = await fetch(`${API}/api/ai_agent`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ prompt, model }),
    });
    const d = await r.json();

    // Remove thinking bubble
    const think = $(thinkId);
    if (think) think.remove();

    // Discriminate between backend errors, model errors, and valid responses
    if (!r.ok || d.ok === false) {
      const errMsg = d.detail || d.error || 'Backend error — check server logs.';
      appendAgentMsg("err", "⚕ agent>", `⚠️ ${escHtml(errMsg)}`);
      agentRunning = false;
      $("agent-send-btn").disabled = false;
      $("agent-send-btn").innerHTML = "<span>▶ Run Agent</span>";
      return;
    }

    let raw;
    if (!d.response) {
      // Model returned empty output — show a clear message with retry
      appendAgentMsg("err", "⚕ agent>", `Model returned no output. The model may still be loading or ran out of context.<br>
        <button class="action-btn" style="margin-top:.5rem;padding:.3rem .7rem;font-size:.8rem" onclick="sendAgentMessage()">↺ Retry</button>`);
      agentRunning = false;
      $("agent-send-btn").disabled = false;
      $("agent-send-btn").innerHTML = "<span>▶ Run Agent</span>";
      return;
    } else {
      raw = d.response;
    }

    const { text, commands } = parseAgentResponse(raw);

    // Render AI explanation
    if (text) {
      let htmlContent = escHtml(text).replace(/\n/g, "<br>");
      let pullModelMatch = raw.match(/ollama pull\s+([a-zA-Z0-9\-_\:\.]+)/i);
      let pullModelName = pullModelMatch ? pullModelMatch[1] : null;
      if (pullModelName && !isOllamaModelDownloaded(pullModelName)) {
        htmlContent += `<div class="ollama-download-block" data-model="${escHtml(pullModelName)}" style="margin-top:0.6rem">
          <button class="primary-btn" style="padding:0.4rem 0.8rem; font-size:0.75rem" onclick="injectOllamaCmd('ollama pull ${escHtml(pullModelName)}', 'Download ${escHtml(pullModelName)} model', 'Low', false)">Download Model ${escHtml(pullModelName)}</button>
        </div>`;
      }
      appendAgentMsg("bot", "⚕ agent>", htmlContent);
    }

    // Render command cards
    if (commands.length > 0) renderAgentCommands(commands);
    else if (!text.trim()) appendAgentMsg("bot", "⚕ agent>", "I couldn't find specific commands for this. Try rephrasing or ask me to 'diagnose and fix [problem]'.");

  } catch (err) {
    const think = $(thinkId);
    if (think) think.remove();
    appendAgentMsg("err", "⚕ agent>",
      `⚠️ Could not reach backend. Is it running?<br><small>${escHtml(String(err))}</small><br>` +
      `<button class="action-btn" style="margin-top:.5rem;padding:.3rem .7rem;font-size:.8rem" onclick="(function(){$('agent-input').value=_lastAgentPrompt;sendAgentMessage();})()">↺ Retry</button>`
    );
  }

  agentRunning = false;
  $("agent-send-btn").disabled = false;
  $("agent-send-btn").innerHTML = "<span>▶ Run Agent</span>";
}



/* ─── COMMAND DICTIONARY & BREAKDOWN ─────────────────────── */
const COMMAND_DICTIONARY = {
  "sudo": "Run command with administrator privileges (Superuser Do)",
  "apt-get": "Advanced Package Tool (Ubuntu/Debian Package Manager)",
  "install": "Subcommand to install packages",
  "-y": "Automatic 'yes' to prompts for non-interactive execution",
  "python3": "Python 3 runtime environment",
  "python3-pip": "Python package installer (pip)",
  "ensurepip": "Bootstraps/installs standard pip library in Python",
  "--upgrade": "Upgrades packages to their latest version",
  "npm": "Node Package Manager (npm)",
  "nodejs": "Node.js JavaScript runtime environment",
  "-g": "Installs package globally",
  "git": "Git version control system CLI",
  "systemctl": "Systemd service manager utility",
  "start": "Starts a background service",
  "enable": "Enables a service to start at boot time",
  "docker": "Docker container runtime engine CLI",
  "docker.io": "Docker engine installation package on Ubuntu",
  "--now": "Runs the action immediately alongside enabling the service",
  "purge": "Uninstall package and completely purge its configuration files",
  "code": "Visual Studio Code command-line helper",
  "default-jdk": "Default Java SE Development Kit (JDK)",
  "JAVA_HOME": "Environment variable storing the path of the Java install directory",
  "rm": "Remove (delete) files or directories",
  "-rf": "Force-delete files/directories recursively",
  "sync": "Forces immediate flush of dirty filesystem buffers to disk",
  "tee": "Redirects command output to files and standard output",
  "/proc/sys/vm/drop_caches": "Kernel control file to release cached system RAM",
  "systemctl list-unit-files": "Lists all installed systemd service configuration files",
  "--state=enabled": "Filters to only show enabled services",
  "--type=service": "Restricts output list to system service units",
  "snap": "Canonical Snapcraft package manager for Linux",
  "winget": "Windows Package Manager",
  "--silent": "Runs installer in background silent/unattended mode",
  "del": "Deletes one or more files in Windows command prompt",
  "autoremove": "Removes packages that were installed as dependencies but are no longer needed",
  "autoclean": "Removes cached .deb files for packages that can no longer be downloaded",
  "ubuntu-drivers": "Tool for detecting and installing proprietary Ubuntu hardware drivers",
  "autoinstall": "Automatically installs the recommended drivers for your hardware",
  "lspci": "Lists all PCI devices (including GPUs, network cards, etc.)",
};

function generateCommandBreakdown(command) {
  if (!command) return "";
  const tokens = [];
  const phrases = [
    "systemctl list-unit-files", "winget install", "python3 -m pip",
    "python3 -m ensurepip", "ubuntu-drivers autoinstall",
  ];

  let processedCmd = command;
  phrases.forEach(phrase => {
    if (processedCmd.toLowerCase().includes(phrase.toLowerCase())) {
      tokens.push({ token: phrase, desc: COMMAND_DICTIONARY[phrase] || "" });
      processedCmd = processedCmd.replace(new RegExp(phrase, "gi"), "");
    }
  });

  processedCmd.split(/\s+/).forEach(word => {
    const clean = word.replace(/[&|"';()\[\]{}]/g, "").trim();
    if (!clean || clean.length < 2) return;
    for (const [key, value] of Object.entries(COMMAND_DICTIONARY)) {
      if (clean.toLowerCase() === key.toLowerCase() || clean.toLowerCase().startsWith(key.toLowerCase() + "=")) {
        if (!tokens.some(t => t.token.toLowerCase() === clean.toLowerCase())) {
          tokens.push({ token: clean, desc: value });
        }
      }
    }
  });

  if (tokens.length === 0) return "";

  let html = `<div class="edu-header">🔍 Command Component Breakdown</div><div class="edu-breakdown">`;
  tokens.forEach(t => {
    html += `<div class="edu-item">
      <span class="edu-token">${escHtml(t.token)}</span>
      <span class="edu-desc">${escHtml(t.desc)}</span>
    </div>`;
  });
  html += `</div>`;
  return html;
}

/* ─── COMMAND MODAL ──────────────────────────────────────── */
function openModal(data) {
  pendingCommand = data;
  const runBtn = $("btn-run-confirm");
  if (runBtn) {
    runBtn.disabled = false;
    runBtn.textContent = "Run This Command";
  }
  $("modal-title").textContent   = data.title   || "Repair Action";
  $("modal-command").textContent = data.command || "";
  $("modal-purpose").textContent = data.purpose || "";
  $("modal-affects").textContent = data.affects || "System";

  const breakdownHtml = generateCommandBreakdown(data.command);
  $("edu-box").innerHTML = `
    <div style="margin-bottom: 0.8rem; line-height: 1.5;">${escHtml(data.purpose || "")}</div>
    ${breakdownHtml}
  `;

  const badge = $("modal-risk-badge");
  badge.textContent = (data.risk || "Low") + " Risk";
  badge.className   = "risk-badge " + (data.risk || "Low");

  $("modal-overlay").classList.remove("hidden");
}

function closeModal(e) {
  if (!e || e.target === $("modal-overlay")) {
    $("modal-overlay").classList.add("hidden");
    pendingCommand = null;
  }
}
function closeModalBtn() { closeModal(); }

async function confirmRun() {
  if (!pendingCommand) return;

  const btn = $("btn-run-confirm");
  btn.disabled    = true;
  btn.textContent = "Running…";

  const progressContainer = $("modal-progress-container");
  const progressFill = $("modal-progress-fill");
  const progressPercent = $("modal-progress-percentage");
  const checklist = $("modal-status-checklist");

  // Reset progress and show it
  progressFill.style.width = "0%";
  progressPercent.textContent = "0%";
  checklist.innerHTML = "";
  progressContainer.classList.remove("hidden");

  const checkSvg = `<svg class="scan-step-svg success" style="width:14px;height:14px;display:inline-block;vertical-align:middle;color:#86efac;"><use href="#icon-check"></use></svg>`;

  // Helper to add checklist steps
  function addStep(bullet, text, state = "active") {
    const step = document.createElement("div");
    step.className = `checklist-step ${state}`;
    const bulletHtml = bullet === "✓" ? checkSvg : bullet;
    step.innerHTML = `
      <span class="step-bullet" style="display:inline-flex;align-items:center;justify-content:center;">${bulletHtml}</span>
      <span>${escHtml(text)}</span>
    `;
    checklist.appendChild(step);
    checklist.scrollTop = checklist.scrollHeight;
    return step;
  }

  // Step 1: Checking safety clearance
  const step1 = addStep("⏳", "Checking safety clearance...");
  progressFill.style.width = "20%";
  progressPercent.textContent = "20%";
  await new Promise(r => setTimeout(r, 600));

  step1.className = "checklist-step completed";
  step1.querySelector(".step-bullet").innerHTML = checkSvg;

  // Step 2: Sudo elevation (if command includes sudo)
  let step2;
  const isSudo = pendingCommand.command.toLowerCase().includes("sudo");
  if (isSudo) {
    step2 = addStep("🔑", "Requesting sudo elevation...");
    progressFill.style.width = "40%";
    progressPercent.textContent = "40%";
    showToast("🔑 Administrative elevation required. Check your desktop for a password prompt!", "ok");
    await new Promise(r => setTimeout(r, 800));
    step2.className = "checklist-step completed";
    step2.querySelector(".step-bullet").innerHTML = checkSvg;
  } else {
    step2 = addStep("✓", "Safety check passed (Low Risk command)", "completed");
    progressFill.style.width = "40%";
    progressPercent.textContent = "40%";
    await new Promise(r => setTimeout(r, 400));
  }

  // Step 3: Executing setup
  const step3 = addStep("⚡", "Executing setup & repair commands...");
  progressFill.style.width = "70%";
  progressPercent.textContent = "70%";

  try {
    const r = await fetch(`${API}/api/execute`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        command: pendingCommand.command,
        risk:    pendingCommand.risk    || "Low",
        title:   pendingCommand.title   || "",
        purpose: pendingCommand.purpose || "",
        action_key: pendingCommand.action_key || "",
      }),
    });

    // Handle HTTP 403 (blocked by safety layer) explicitly
    if (r.status === 403) {
      const body = await r.json().catch(() => ({}));
      const reason = body.detail?.message || body.detail?.reason || body.detail || "Blocked by safety layer.";
      step3.className = "checklist-step completed";
      step3.querySelector(".step-bullet").textContent = "🛡";
      addStep("🛡", `Blocked: ${reason.slice(0, 100)}`, "completed");
      progressFill.style.width = "100%";
      progressPercent.textContent = "100%";
      showToast(`🛡 Command blocked: ${reason.slice(0, 120)}`, "err");
      progressContainer.classList.add("hidden");
      btn.disabled = false;
      btn.textContent = "Run This Command";
      $("modal-overlay").classList.add("hidden");
      pendingCommand = null;
      return;
    }

    const d = await r.json();

    if (d.ok) {
      step3.className = "checklist-step completed";
      step3.querySelector(".step-bullet").innerHTML = checkSvg;

      const step4 = addStep("🎉", "Success! Action completed.", "completed");
      progressFill.style.width = "100%";
      progressPercent.textContent = "100%";
      await new Promise(r => setTimeout(r, 1000));

      if (pendingCommand && pendingCommand.title === "Update Driver Packages") {
        window.kernelDriversUpdated = true;
      }

      if (pendingCommand && pendingCommand.affects) {
        const installedApp = pendingCommand.affects.toLowerCase();
        const alreadyExists = DEV_TOOLS.some(t => t.name.toLowerCase() === installedApp);
        if (!alreadyExists) {
          const name = pendingCommand.affects.charAt(0).toUpperCase() + pendingCommand.affects.slice(1);
          const icon = name.slice(0, 2);
          const statusKey = installedApp;
          const hint = `${name} missing`;
          const description = pendingCommand.purpose || `${name} developer tool.`;
          DEV_TOOLS.push({ icon, name, statusKey, hint, description });
        }
        toolStatusCache = null;
        await loadDevToolCards(true);
      }

      showToast("✓ Command completed successfully", "ok");
    } else {
      step3.className = "checklist-step completed";
      step3.querySelector(".step-bullet").textContent = "⚠";
      addStep("❌", "Command finished with errors.", "completed");
      
      const stderr = d.stderr ? d.stderr.trim() : "";
      const stdout = d.stdout ? d.stdout.trim() : "";
      const message = stderr || stdout || "Command finished with errors. Check Action Logs.";
      const errorMessage = message.length > 200 ? message.substring(0, 200) + "..." : message;
      if (message.toLowerCase().includes("could not connect to ollama server")) {
        showToast("⚠ Ollama server is not running. Start it with 'ollama serve' and try again.", "err");
      } else {
        showToast(`⚠ Error: ${errorMessage}`, "err");
      }

      // Auto-repair notification: SHCE queued a fix automatically, start auto-redirect sequence
      if (d.shce_queue_id) {
        autoNavigateToRepairQueue(d.shce_queue_id);
      }
      await new Promise(r => setTimeout(r, 2000));
    }
  } catch (err) {
    step3.className = "checklist-step completed";
    step3.querySelector(".step-bullet").textContent = "❌";
    addStep("❌", `Connection failed: ${err.message}`, "completed");
    showToast("⚠ Backend unreachable. Is it running?", "err");
    await new Promise(r => setTimeout(r, 2000));
  }

  // Clean up
  progressContainer.classList.add("hidden");
  btn.disabled    = false;
  btn.textContent = "✓ Run This Command";
  $("modal-overlay").classList.add("hidden");
  pendingCommand = null;

  // Refresh active view dynamically to show status update immediately
  await refreshActiveView();
}

/* ─── LOGS ───────────────────────────────────────────────── */
function formatLogEntry(e) {
  const ts = e.timestamp ? new Date(e.timestamp).toLocaleString() : "—";
  const isError = e.action === "FAILED" || e.action === "BLOCKED" || e.action === "ERROR";
  
  // Determine Error Source
  let errorSource = "N/A";
  if (isError) {
    errorSource = e.error_source || (e.self_healing && e.self_healing.source) || "System Control Layer";
  }
  
  // Determine Functionality Affected
  let affectedFunc = "General System Maintenance";
  if (e.command) {
    const cmdL = e.command.toLowerCase();
    if (cmdL.includes("apt") || cmdL.includes("dpkg") || cmdL.includes("upgrade")) {
      affectedFunc = "Package Manager";
    } else if (cmdL.includes("docker")) {
      affectedFunc = "Docker Daemon";
    } else if (cmdL.includes("nvidia") || cmdL.includes("ubuntu-drivers")) {
      affectedFunc = "Drivers Page";
    } else if (cmdL.includes("pip") || cmdL.includes("python")) {
      affectedFunc = "Python Environment";
    } else if (cmdL.includes("npm") || cmdL.includes("node")) {
      affectedFunc = "Node.js Environment";
    } else if (cmdL.includes("drop_caches")) {
      affectedFunc = "Optimize Page";
    }
  } else if (e.action === "LOGS_CLEARED" || e.action === "LOGS_DELETED") {
    affectedFunc = "Control Center (Logs)";
  }
  
  let shStatus = "N/A";
  let resolution = "Completed";
  
  if (isError) {
    shStatus = e.self_healing ? e.self_healing.status : "Unsupported";
    resolution = e.self_healing ? (e.self_healing.status === "Healing Successful" ? "Resolved" : "Unresolved") : "Unresolved";
  } else if (e.action === "SELF_HEAL") {
    shStatus = e.detail && e.detail.includes("Successful") ? "Healing Successful" : "Healing Failed";
    resolution = shStatus === "Healing Successful" ? "Resolved" : "Unresolved";
  }
  
  const icon = isError ? "❌" : e.action === "SELF_HEAL" ? "⚕️" : "ℹ️";
  
  let html = `
    <div class="log-item-header" style="display:flex; justify-content:space-between; align-items:center; font-size:0.8rem; border-bottom:1px solid rgba(255,255,255,0.04); padding-bottom:0.3rem; margin-bottom:0.4rem;">
      <span class="log-time" style="color:var(--text-3)">🕒 ${escHtml(ts)}</span>
      <span class="log-action-badge ${e.action.toLowerCase()}" style="font-weight:600; padding:0.1rem 0.4rem; border-radius:3px; background:rgba(255,255,255,0.06);">${escHtml(e.action)}</span>
    </div>
    <div class="log-body">
      <div style="font-weight:600; margin-bottom:0.3rem; color:var(--text-1);">${icon} ${escHtml(e.friendly_summary || e.command || "Logged Action")}</div>
      ${e.command && e.friendly_summary && e.friendly_summary !== e.command ? `<code style="display:block; font-size:0.75rem; background:rgba(0,0,0,0.2); padding:0.25rem; border-radius:4px; margin-bottom:0.3rem; font-family:var(--mono); color:#cbd5e1;">${escHtml(e.command)}</code>` : ""}
      ${e.detail && e.detail !== e.friendly_summary && e.detail !== e.command ? `<div style="font-size:0.78rem; color:var(--text-2); margin-top:0.2rem; background:rgba(255,255,255,0.01); border:1px solid rgba(255,255,255,0.03); padding:0.3rem; border-radius:4px;">Detail: ${escHtml(e.detail)}</div>` : ""}
    </div>
    <div class="log-meta-grid" style="display:grid; grid-template-columns: repeat(auto-fit, minmax(140px, 1fr)); gap:0.4rem; margin-top:0.6rem; padding-top:0.5rem; border-top:1px dashed rgba(255,255,255,0.05); font-size:0.72rem; color:var(--text-3);">
      <div><strong>Error Source:</strong> ${escHtml(errorSource)}</div>
      <div><strong>Function Affected:</strong> ${escHtml(affectedFunc)}</div>
      <div><strong>Self-Healing:</strong> <span class="sh-status-${shStatus.toLowerCase().replace(/ /g, '-')}" style="font-weight:600; color: ${shStatus.includes('Successful') ? '#79f2c0' : shStatus.includes('Failed') ? '#fca5a5' : '#cbd5e1'}">${escHtml(shStatus)}</span></div>
      <div><strong>Status:</strong> <span class="res-status-${resolution.toLowerCase()}" style="font-weight:600; color: ${resolution === 'Resolved' || resolution === 'Completed' ? '#79f2c0' : '#fca5a5'}">${escHtml(resolution)}</span></div>
    </div>
  `;
  return html;
}

async function loadLogs() {
  const list = $("log-list");
  if (!list) return;
  list.innerHTML = `<div class="issue-card"><div class="issue-body"><span class="spinner"></span> Loading logs…</div></div>`;
  try {
    const r = await fetch(`${API}/api/logs`);
    const d = await r.json();
    logEntries = (d.logs || []).map((line, index) => {
      let parsed;
      if (line && typeof line === "object") {
        parsed = line;
      } else {
        try {
          parsed = JSON.parse(line);
        } catch {
          parsed = { action: "LOG", command: line, detail: "", timestamp: "" };
        }
      }
      return { index, raw: line, parsed };
    });
    if (!logEntries.length) {
      list.innerHTML = `<div class="issue-card"><div class="issue-body" style="color:var(--text-2)">No actions logged yet.</div></div>`;
      return;
    }
    list.innerHTML = logEntries.map(entry => `
      <div class="log-entry" style="margin-bottom:0.8rem; padding:0.8rem; border-radius:var(--radius); background:rgba(255,255,255,0.02); border:1px solid rgba(255,255,255,0.06);">
        <span>${formatLogEntry(entry.parsed)}</span>
      </div>
    `).join("");
    const logBox = $("log-box");
    if (logBox) {
      logBox.textContent = logEntries.map(entry => {
        const e = entry.parsed;
        return `${e.action} » ${e.friendly_summary || e.command || ""}`;
      }).join("\n");
    }
  } catch (err) {
    list.innerHTML = `<div class="issue-card"><div class="issue-body" style="color:var(--risk-high)">Backend unreachable. (${err.message})</div></div>`;
  }
}

async function deleteSelectedLogs() {
  const selected = [...document.querySelectorAll(".log-select:checked")].map(el => Number(el.dataset.logIndex));
  if (!selected.length) {
    showToast("Select at least one log entry to delete.", "err");
    return;
  }
  if (!confirm(`Delete ${selected.length} selected log entr${selected.length === 1 ? "y" : "ies"}? This cannot be undone.`)) return;
  try {
    const r = await fetch(`${API}/api/logs/delete`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ confirm: true, all: false, indices: selected }),
    });
    const d = await r.json();
    if (d.ok) {
      showToast(`Deleted ${d.removed || selected.length} log entr${d.removed === 1 ? "y" : "ies"}.`, "ok");
      await loadLogs();
    } else {
      showToast("Failed to delete selected logs.", "err");
    }
  } catch (err) {
    showToast(`Delete failed: ${err.message}`, "err");
  }
}

async function deleteAllLogs() {
  if (!confirm("Delete ALL logs? This cannot be undone.")) return;
  try {
    const r = await fetch(`${API}/api/logs/delete`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ confirm: true, all: true, indices: [] }),
    });
    const d = await r.json();
    if (d.ok) {
      showToast(`Deleted ${d.removed || 0} log entries.`, "ok");
      await loadLogs();
      loadRecentLogsInDrawer();
    }
  } catch (err) {
    showToast(`Delete failed: ${err.message}`, "err");
  }
}

// ── Performance Metrics Dashboard (Task 14.1/14.2/14.3) ──────────────────────
async function loadPerformanceMetrics() {
  const panel = $("perf-metrics-panel");
  const body  = $("perf-metrics-body");
  if (!panel || !body) return;
  panel.classList.remove("hidden");
  body.innerHTML = `<span class="spinner" style="margin:.5rem"></span> Loading…`;
  try {
    const r = await fetch(`${API}/api/metrics`);
    const d = await r.json();
    if (!d.ok) { body.innerHTML = `<span style="color:var(--risk-high)">Failed to load metrics.</span>`; return; }
    const mem = d.memory || {};
    const err = d.errors || {};
    const sys = d.system || {};
    const warn = d.warnings || [];
    const tile = (label, value, color = "var(--text-1)") =>
      `<div style="background:rgba(255,255,255,0.03);border:1px solid rgba(255,255,255,0.07);border-radius:var(--radius-sm);padding:.65rem .9rem;">
        <div style="font-size:.7rem;color:var(--text-3);text-transform:uppercase;letter-spacing:.04em;margin-bottom:.2rem;">${escHtml(label)}</div>
        <div style="font-size:1rem;font-weight:700;color:${color};">${escHtml(String(value))}</div>
      </div>`;
    const memColor = (mem.percent || 0) > 85 ? "var(--risk-high)" : (mem.percent || 0) > 60 ? "#fde047" : "var(--apple-mint)";
    const cpuColor = (sys.cpu_percent || 0) > 90 ? "var(--risk-high)" : (sys.cpu_percent || 0) > 60 ? "#fde047" : "var(--apple-mint)";
    body.innerHTML = [
      tile("RAM Used",     `${mem.used_gb || 0} / ${mem.total_gb || 0} GB`, memColor),
      tile("RAM %",        `${mem.percent || 0}%`, memColor),
      tile("CPU %",        `${sys.cpu_percent || 0}%`, cpuColor),
      tile("Disk Used",    `${sys.disk_used_gb || 0} / ${sys.disk_total_gb || 0} GB`),
      tile("Errors Total", err.total_captured || 0),
      tile("Pending Errors", err.pending || 0, (err.pending || 0) > 5 ? "#fde047" : "var(--text-1)"),
      tile("Fixes Applied", err.fixes_executed || 0, "var(--apple-mint)"),
      tile("Fix Rate",     `${err.fix_success_rate || 0}%`, "var(--apple-cyan)"),
    ].join("");
    if (warn.length) {
      body.innerHTML += `<div style="grid-column:1/-1;margin-top:.5rem;padding:.5rem .75rem;border-radius:var(--radius-sm);background:rgba(255,159,10,.08);border:1px solid rgba(255,159,10,.3);color:#fde047;font-size:.8rem;">
        ⚠ ${warn.map(escHtml).join(" · ")}
      </div>`;
    }
  } catch(err) {
    body.innerHTML = `<span style="color:var(--risk-high)">Could not load metrics: ${escHtml(err.message)}</span>`;
  }
}
window.loadPerformanceMetrics = loadPerformanceMetrics;

async function clearLogsFromSettings() {
  if (!confirm("Clear all logs from the log file? This cannot be undone.")) return;
  try {
    const r = await fetch(`${API}/api/logs/clear`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ confirm: true }),
    });
    const d = await r.json();
    if (d.ok) {
      showToast(`Cleared ${d.removed || 0} log entries.`, "ok");
      if (activeViewName === "logs") await loadLogs();
      loadRecentLogsInDrawer();
    }
  } catch (err) {
    showToast(`Clear failed: ${err.message}`, "err");
  }
}


async function exportLogs() {
  try {
    const r = await fetch(`${API}/api/logs/export`);
    const d = await r.json();
    if (!d.ok || !d.content) {
      showToast("Nothing to export.", "err");
      return;
    }
    const blob = new Blob([d.content], { type: "text/plain;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = d.filename || "pc_doctor_logs.txt";
    link.click();
    URL.revokeObjectURL(url);
    showToast("Logs exported.", "ok");
  } catch (err) {
    showToast(`Export failed: ${err.message}`, "err");
  }
}

function toggleHelpCenter() {
  const panel = $("settings-help-panel");
  const btn = $("settings-help-btn");
  if (!panel) return;
  const opening = panel.classList.contains("hidden");
  if (opening) {
    panel.innerHTML = `
      <h4>Application Overview</h4>
      <p>PC Doc is an offline-first system maintenance assistant. It adapts repair, optimization, and developer commands to your operating system and records every action for transparency.</p>
      <h4>First-Time Setup</h4>
      <ol>
        <li>Start the backend from Settings or the top bar.</li>
        <li>Open the OS Adaptation tab from the sidebar footer to confirm detected OS and package manager.</li>
        <li>Click <strong>Refresh All</strong> to validate command mappings.</li>
        <li>Run a Scan, then use Repair or Optimize as needed.</li>
      </ol>
      <h4>Feature Guide</h4>
      <ul>
        <li><strong>Repair</strong> — Fixes common system problems and configuration issues.</li>
        <li><strong>Optimize</strong> — Improves performance with OS-specific maintenance commands.</li>
        <li><strong>Dev Tools</strong> — Suggests development-related tools and utilities.</li>
        <li><strong>Drivers</strong> — Displays hardware and driver information with GPU usage.</li>
        <li><strong>OS Adaptation</strong> — Shows adaptation progress, compatibility, and command mappings.</li>
      </ul>
      <h4>Troubleshooting</h4>
      <ul>
        <li><strong>Update System Packages blocked</strong> — Open Optimize, refresh commands, and run only the adapted package update. Check Action Logs for block reason and recommended fix.</li>
        <li><strong>Integrated GPU shows 0%</strong> — This often means the GPU is idle, not broken. Check Integrated GPU Status on the Drivers page.</li>
        <li><strong>Dev Tools suggestions repeat</strong> — Use Refresh Suggestions; the backend rotates the pool and excludes recently shown tools.</li>
        <li><strong>Backend offline</strong> — Start the backend from Settings and confirm port 8765 is free.</li>
      </ul>
    `;
    panel.classList.remove("hidden");
    if (btn) btn.textContent = "Close Help";
  } else {
    panel.classList.add("hidden");
    if (btn) btn.textContent = "Open Help";
  }
}

/* ─── TOAST ──────────────────────────────────────────────── */
let toastTimer;
function showToast(msg, type = "ok") {
  const lowercaseMsg = (msg || "").toString().toLowerCase();
  const isNetworkOrPipe = lowercaseMsg.includes("epipe") ||
                          lowercaseMsg.includes("broken pipe") ||
                          lowercaseMsg.includes("eio") ||
                          lowercaseMsg.includes("econnreset") ||
                          lowercaseMsg.includes("econnrefused") ||
                          lowercaseMsg.includes("network") ||
                          lowercaseMsg.includes("fetch") ||
                          lowercaseMsg.includes("connection closed") ||
                          lowercaseMsg.includes("load failed") ||
                          lowercaseMsg.includes("failed to fetch") ||
                          lowercaseMsg.includes("typeerror: load failed");
  if (isNetworkOrPipe && type === "err") {
    console.warn("[PC Doctor] Network/IPC error toast suppressed:", msg);
    return;
  }
  const t = $("toast");
  t.textContent = msg;
  t.className   = `toast ${type}`;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => t.classList.add("hidden"), 3500);
}

/* ─── UTILS ──────────────────────────────────────────────── */
function escHtml(str) {
  return String(str)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

/* ─── KEYBOARD ────────────────────────────────────────────── */
document.addEventListener("keydown", e => {
  if (e.key === "Escape") {
    closeModalBtn();
    closeStartupModalBtn();
    closeAgentModalBtn();
    closeSettingsDrawer();
  }
});

/* ─── SETTINGS DRAWER ────────────────────────────────────── */
function openSettingsDrawer() {
  $('settings-drawer').classList.add('active');
  $('settings-drawer-overlay').classList.add('active');
  loadRecentLogsInDrawer();
}

function closeSettingsDrawer() {
  $('settings-drawer').classList.remove('active');
  $('settings-drawer-overlay').classList.remove('active');
}

async function loadRecentLogsInDrawer() {
  const container = $("drawer-recent-logs-list");
  if (!container) return;
  container.innerHTML = `<div style="color:var(--text-3); font-size:0.75rem;"><span class="spinner" style="width:12px; height:12px; vertical-align:middle; margin-right:4px;"></span> Loading recent logs…</div>`;
  try {
    const r = await fetch(`${API}/api/logs`);
    const d = await r.json();
    const logs = d.logs || [];
    if (!logs.length) {
      container.innerHTML = `<div style="color:var(--text-3); font-size:0.75rem; font-style:italic;">No recent actions logged.</div>`;
      return;
    }
    // Take the first 3 (newest first from backend)
    const recent = logs.slice(0, 3).map(line => {
      if (line && typeof line === "object") {
        return line;
      }
      try {
        return JSON.parse(line);
      } catch {
        return { action: "LOG", command: line, detail: "", timestamp: "" };
      }
    });
    
    container.innerHTML = recent.map(entry => {
      return `<div class="recent-log-item">${formatLogEntry(entry)}</div>`;
    }).join("");
  } catch (err) {
    container.innerHTML = `<div style="color:var(--risk-high); font-size:0.75rem;">Failed to load logs.</div>`;
  }
}


document.getElementById('settings-toggle-btn')?.addEventListener('click', openSettingsDrawer);
document.getElementById('settings-close-btn')?.addEventListener('click', closeSettingsDrawer);
document.getElementById('settings-drawer-overlay')?.addEventListener('click', closeSettingsDrawer);

/* ─── THEME MANAGEMENT ───────────────────────────────────── */
let currentTheme = localStorage.getItem('theme') || 'dark';

function setTheme(theme) {
  currentTheme = theme;
  localStorage.setItem('theme', theme);
  
  if (theme === 'light') {
    document.documentElement.classList.add('light-theme');
    const lightBtn = $('theme-light-btn');
    const darkBtn = $('theme-dark-btn');
    if (lightBtn) lightBtn.classList.add('active');
    if (darkBtn) darkBtn.classList.remove('active');
  } else {
    document.documentElement.classList.remove('light-theme');
    const lightBtn = $('theme-light-btn');
    const darkBtn = $('theme-dark-btn');
    if (darkBtn) darkBtn.classList.add('active');
    if (lightBtn) lightBtn.classList.remove('active');
  }
  
  if (typeof updateTheme === 'function') {
    updateTheme(theme);
  }
}

// Expose to window for inline onclick attributes
window.setTheme = setTheme;

function initNavSetupState() {
  const migrationKey = "pc_doctor_nav_setup_v1";
  if (!localStorage.getItem(migrationKey)) {
    if (localStorage.getItem("pc_doctor_first_install") !== "true") {
      localStorage.setItem(SETUP_COMPLETE_KEY, "true");
    }
    localStorage.setItem(migrationKey, "true");
  }
  updateOsOvalBar();
}

/* ─── SELF-HEALING & ADAPTATION DASHBOARD ────────────────── */
async function refreshSelfHealingDashboard() {
  const successRateEl = $("sh-analytics-success-rate");
  const attemptsRatioEl = $("sh-analytics-attempts-ratio");
  const rollbacksEl = $("sh-analytics-rollbacks");
  const trustedEl = $("sh-analytics-trusted");
  const experimentalEl = $("sh-analytics-experimental");
  const degradedEl = $("sh-analytics-degraded");
  const pendingList = $("sh-pending-list");
  const registryBody = $("sh-registry-body");

  try {
    const res = await fetch(`${API}/api/self-healing/status`);
    const data = await res.json();
    if (!data.ok) throw new Error("Failed to load self-healing status");

    const analytics = data.analytics || {};
    
    if (successRateEl) successRateEl.textContent = `${Math.round((analytics.success_rate || 0) * 100)}%`;
    if (attemptsRatioEl) attemptsRatioEl.textContent = `${analytics.success_count || 0} of ${analytics.total_attempts || 0} attempts successful`;
    if (rollbacksEl) rollbacksEl.textContent = `${analytics.rollback_count || 0}`;
    if (trustedEl) trustedEl.textContent = `${analytics.trusted_count || 0}`;
    if (experimentalEl) experimentalEl.textContent = `${analytics.experimental_count || 0}`;
    if (degradedEl) degradedEl.textContent = `${analytics.degraded_count || 0}`;

    if (pendingList) {
      const pendingAttempts = (data.attempts || []).filter(att => att.result === "Waiting User Approval");
      if (pendingAttempts.length === 0) {
        pendingList.innerHTML = `<div class="empty-row" style="color: var(--text-2); font-size: 0.85rem; padding: 1rem;">No pending self-healing recommendations.</div>`;
      } else {
        pendingList.innerHTML = pendingAttempts.map(att => {
          const isDangerous = att.safety_class === "Dangerous";
          const classBadgeColor = isDangerous ? "var(--risk-high)" : att.safety_class === "Caution" ? "var(--risk-medium)" : "var(--risk-low)";
          
          return `
            <div class="issue-card" style="display: flex; flex-direction: column; gap: 0.6rem; align-items: stretch; border: 1px solid rgba(255,255,255,0.08); padding: 1rem;">
              <div style="display: flex; justify-content: space-between; align-items: center;">
                <strong style="color: var(--risk-high); font-size: 0.9rem;">⚠️ Unresolved Failure Detected</strong>
                <span class="risk-badge" style="background: ${classBadgeColor}; color: #fff; font-size: 0.72rem; padding: 0.15rem 0.45rem; border-radius: 4px;">${escHtml(att.safety_class)}</span>
              </div>
              <div style="font-size: 0.82rem; color: var(--text-2); background: rgba(255,255,255,0.02); padding: 0.5rem; border-radius: 4px; border: 1px solid rgba(255,255,255,0.04); font-family: var(--mono); white-space: pre-wrap; word-break: break-all;">${escHtml(att.error_message)}</div>
              
              <div style="margin-top: 0.25rem;">
                <div style="font-size: 0.78rem; font-weight: 600; color: var(--text-1);">Recommended Command:</div>
                <code style="display: block; background: rgba(0,0,0,0.2); border: 1px solid rgba(255,255,255,0.1); padding: 0.4rem; border-radius: 4px; font-size: 0.8rem; color: #cbd5e1; margin-top: 0.25rem; font-family: var(--mono);">${escHtml(att.attempted_fix)}</code>
              </div>

              ${isDangerous ? `
                <div style="font-size: 0.75rem; color: #fca5a5; background: rgba(239,68,68,0.08); padding: 0.5rem; border-radius: 4px; border: 1px solid rgba(239,68,68,0.15);">
                  <strong>⚠️ Critical System Command Warning:</strong> This action targets system package upgrades or service modifications. It requires manual double confirmation before running.
                </div>
              ` : ''}

              <div style="font-size: 0.75rem; color: var(--text-3);">Source: ${escHtml(att.fix_source)} | Sandbox Status: <strong style="color: #79f2c0;">Passed</strong></div>

              <div style="display: flex; gap: 0.5rem; justify-content: flex-end; margin-top: 0.4rem;">
                <button class="primary-btn" style="padding: 0.35rem 0.85rem; font-size: 0.78rem; background: rgba(121,242,192,0.15); border-color: rgba(121,242,192,0.3); color: #79f2c0;" onclick="approveSelfHealing(${att.id}, '${att.safety_class}', ${escHtml(JSON.stringify(att.attempted_fix))})">Approve &amp; Run</button>
                <button class="action-btn" style="padding: 0.35rem 0.85rem; font-size: 0.78rem;" onclick="archiveSelfHealing(${att.id})">Ignore</button>
              </div>
            </div>
          `;
        }).join("");
      }
    }

    if (registryBody) {
      const mappings = data.registry_mappings || [];
      if (mappings.length === 0) {
        registryBody.innerHTML = `<tr><td colspan="3" class="empty-row" style="text-align: center; color: var(--text-2); padding: 1rem;">No learned commands in registry yet.</td></tr>`;
      } else {
        registryBody.innerHTML = mappings.map(m => `
          <tr style="border-bottom: 1px solid rgba(255,255,255,0.04);">
            <td style="padding: 0.45rem; font-family: var(--mono); font-size: 0.75rem; color: var(--text-2);">${escHtml(m.failed_command)}</td>
            <td style="padding: 0.45rem; font-family: var(--mono); font-size: 0.75rem; color: #79f2c0;">${escHtml(m.replacement_command)}</td>
            <td style="padding: 0.45rem; text-align: center;"><span style="font-size: 0.7rem; padding: 0.1rem 0.35rem; border-radius: 4px; background: rgba(121,242,192,0.1); border: 1px solid rgba(121,242,192,0.25); color: #79f2c0;">Active Sync</span></td>
          </tr>
        `).join("");
      }
    }

  } catch (err) {
    console.error("Failed to refresh self-healing dashboard:", err);
  }
}

async function approveSelfHealing(attemptId, safetyClass, commandText) {
  if (safetyClass === "Dangerous") {
    const firstConfirm = confirm(`[CRITICAL WARNING] The following command is classified as DANGEROUS:\n\n${commandText}\n\nRunning this command may modify kernel configs or system-level settings. Do you want to proceed?`);
    if (!firstConfirm) return;
    
    const secondConfirm = confirm(`[SECONDARY CONFIRMATION REQUIRED]\nAre you absolutely certain you want to execute this change? This action cannot be undone and may affect OS stability.`);
    if (!secondConfirm) return;
  }

  showToast("Executing repair...", "ok");
  try {
    const res = await fetch(`${API}/api/self-healing/approve`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ attempt_id: attemptId, confirm_dangerous: true })
    });
    const data = await res.json();
    if (data.ok) {
      showToast("Self-healing successful!", "ok");
      refreshSelfHealingDashboard();
      loadDashboardDetails();
    } else {
      if (data.requires_secondary_confirmation) {
        showToast("Dangerous fix requires confirmation.", "err");
      } else {
        showToast(`Execution failed: ${data.stderr || data.result || "Unknown error"}`, "err");
        refreshSelfHealingDashboard();
        loadDashboardDetails();
      }
    }
  } catch (err) {
    showToast(`Error: ${err.message}`, "err");
  }
}

async function archiveSelfHealing(attemptId) {
  try {
    const res = await fetch(`${API}/api/self-healing/archive`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ attempt_id: attemptId })
    });
    const data = await res.json();
    if (data.ok) {
      showToast("Recommendation discarded.", "ok");
      refreshSelfHealingDashboard();
    }
  } catch (err) {
    showToast(`Error: ${err.message}`, "err");
  }
}

let ollamaStatusChecking = false;
let ollamaStatusInterval = null;

async function checkOllamaServiceStatus() {
  if (ollamaStatusChecking) return;
  ollamaStatusChecking = true;
  
  try {
    const r = await fetch(`${API}/api/ollama/status`);
    const d = await r.json();
    
    const dot = $("ollama-service-status-dot");
    const text = $("ollama-service-status-text");
    const btn = $("btn-ollama-service-toggle");
    const agentInput = $("agent-input");
    
    if (dot && text && btn) {
      if (d.running) {
        window.downloadedOllamaModels = d.models || [];
        renderOllamaPanel();
        
        // Clean up download buttons for models that are now downloaded
        document.querySelectorAll(".ollama-download-block").forEach(el => {
          const modelName = el.dataset.model;
          if (modelName && isOllamaModelDownloaded(modelName)) {
            el.remove();
          }
        });

        dot.style.backgroundColor = "#10b981"; // green
        text.textContent = d.starting ? "Ollama Server: Starting..." : "Ollama Server: Running";
        text.style.color = "#a7f3d0";
        btn.textContent = "Stop Server";
        btn.style.background = "rgba(239,68,68,0.1)";
        btn.style.borderColor = "rgba(239,68,68,0.3)";
        btn.style.color = "#fca5a5";

        // Server is running — restore input
        if (agentInput) {
          agentInput.classList.remove("server-offline");
          agentInput.placeholder = "Describe your PC problem…";
        }
      } else {
        dot.style.backgroundColor = "#ef4444"; // red
        text.textContent = "Ollama Server: Stopped";
        text.style.color = "#fca5a5";
        btn.textContent = "Start Server";
        btn.style.background = "rgba(16,185,129,0.1)";
        btn.style.borderColor = "rgba(16,185,129,0.3)";
        btn.style.color = "#a7f3d0";

        // Server is stopped — dim input and show hint
        if (agentInput) {
          agentInput.classList.add("server-offline");
          agentInput.placeholder = "Start the Ollama server first…";
        }
      }
    }
  } catch (err) {
    console.error("Error checking Ollama status:", err);
  } finally {
    ollamaStatusChecking = false;
  }
}

async function toggleOllamaService() {
  const btn = $("btn-ollama-service-toggle");
  if (!btn) return;
  btn.disabled = true;
  btn.textContent = "Processing...";
  
  try {
    const statusRes = await fetch(`${API}/api/ollama/status`);
    const statusData = await statusRes.json();
    
    const action = statusData.running ? "stop" : "start";
    showToast(`${action === "start" ? "Starting" : "Stopping"} Ollama server...`, "ok");
    
    const r = await fetch(`${API}/api/ollama/${action}`, { method: "POST" });
    const d = await r.json();
    
    if (d.ok || r.ok) {
      showToast(`✓ Ollama server ${action === "start" ? "started" : "stopped"}.`, "ok");
    } else {
      showToast(`Failed to ${action} Ollama: ${d.detail || "Unknown error"}`, "err");
    }
  } catch (err) {
    showToast(`Connection failed: ${err.message}`, "err");
  } finally {
    btn.disabled = false;
    await checkOllamaServiceStatus();
  }
}

window.toggleOllamaService = toggleOllamaService;
window.checkOllamaServiceStatus = checkOllamaServiceStatus;
window.refreshSelfHealingDashboard = refreshSelfHealingDashboard;
window.approveSelfHealing = approveSelfHealing;
window.archiveSelfHealing = archiveSelfHealing;


/* ─── INIT ───────────────────────────────────────────────── */
(async () => {
  initNavSetupState();
  setTheme(currentTheme);          // load active theme
  if (window.desktop?.getBackendStatus) {
    try {
      updateBackendUI(await window.desktop.getBackendStatus());
    } catch (_) {
      updateBackendUI('offline');
    }
  } else {
    // In Tauri, backend is auto-started by the Rust side.
    // Set to 'starting' immediately so the UI shows the right state.
    updateBackendUI('starting');

    // After a short delay, probe the backend in case it was already running
    // from a previous session – this avoids a 20 s wait for the Tauri event.
    setTimeout(async () => {
      if (backendState === 'starting') {
        const alive = await fetch(`${API}/health`).then(r => r.ok).catch(() => false);
        if (alive) {
          updateBackendUI('external');
          await checkBackend();
          await loadDashboardDetails();
        }
      }
    }, 3000);
  }

  // Run an immediate checkBackend unless Tauri is still in its startup window.
  // In browser/Electron mode this runs immediately.
  if (backendState !== 'starting') {
    await checkBackend();
  }

  fetchAdaptationStatus(false);
  fetchRecipes();                  // pre-warm
  fetchSystemUpdateCommand(false);
  renderOllamaPanel();             // build Ollama quick-commands panel

  // Poll every 8 s regardless of backendState so the dashboard auto-recovers
  // after a restart without needing the user to click anything.
  setInterval(async () => {
    const wasOffline = backendState === 'offline' || backendState === 'error';
    await checkBackend();
    // If we just came back online, also reload the dashboard data.
    if (wasOffline && (backendState === 'online' || backendState === 'external')) {
      await loadDashboardDetails();
    }
  }, 8000);

  switchView("dashboard");
})();

// ── Cleanup on unload — clear all polling intervals ──────────────────────────
window.addEventListener('beforeunload', () => {
  stopGpuUsageRefresh();
  stopSHCEPolling();
  if (ollamaStatusInterval) {
    clearInterval(ollamaStatusInterval);
    ollamaStatusInterval = null;
  }
});

/* ══════════════════════════════════════════════════════════════════
   SHCE CONTROL CENTER — JavaScript
   Self-Healing Core Engine UI layer
   ══════════════════════════════════════════════════════════════════ */

// ── State ──────────────────────────────────────────────────────────
let _shceTabCurrent = "overview";
let _shcePollTimer = null;
let _shceKBEntries = [];          // cached for live search

/* ── Unified Control Center Tab Controller ─────────────────────────
   ControlCenterTabs provides consistent switching logic, transition
   animations (300ms), and state management for all Control Center tabs.
   Satisfies Requirements 1.1, 1.2, 1.3, 1.5.
──────────────────────────────────────────────────────────────────── */
class ControlCenterTabs {
  constructor() {
    this.tabs = ['overview', 'queue', 'errors', 'knowledge', 'history', 'environment'];
    this.activeTab = 'overview';
    this.transitionDuration = 300; // ms — consistent across all tabs
    this._transitioning = false;
  }

  /**
   * Switch to the given tab with consistent transition animation and
   * lazy-load its content.  All tabs go through this same code path so
   * the Error Monitor tab behaves identically to Overview, Repair Queue, etc.
   */
  switchTab(tabId) {
    if (!this.tabs.includes(tabId)) {
      console.warn(`[ControlCenterTabs] Unknown tab: ${tabId}`);
      return;
    }

    // Guard against rapid successive calls during an in-flight transition
    if (this._transitioning && tabId === this.activeTab) return;

    const previousTab = this.activeTab;
    this.activeTab = tabId;

    // Sync module-level state variable used by polling and refresh logic
    _shceTabCurrent = tabId;

    // ── Update tab button active states ────────────────────────
    document.querySelectorAll('.shce-tab').forEach(btn => {
      btn.classList.remove('active');
      btn.setAttribute('aria-selected', 'false');
    });
    const activeBtn = document.getElementById('shce-tab-' + tabId);
    if (activeBtn) {
      activeBtn.classList.add('active');
      activeBtn.setAttribute('aria-selected', 'true');
    }

    // ── Animate out the current section, then animate in the new one ──
    const outSection = document.getElementById('shce-section-' + previousTab);
    const inSection  = document.getElementById('shce-section-' + tabId);

    if (!inSection) return;

    // Remove active from all panels immediately so state is always consistent
    document.querySelectorAll('.shce-panel-section').forEach(s => {
      if (s !== outSection) {
        s.classList.remove('active');
        s.style.opacity = '';
        s.style.transform = '';
        s.style.transition = '';
      }
    });

    if (outSection && outSection !== inSection && outSection.classList.contains('active')) {
      // Fade-out the leaving panel in parallel with fade-in of new panel
      this._transitioning = true;
      outSection.style.transition = `opacity ${this.transitionDuration}ms cubic-bezier(0.4,0,0.2,1), transform ${this.transitionDuration}ms cubic-bezier(0.4,0,0.2,1)`;
      outSection.style.opacity = '0';
      outSection.style.transform = 'translateY(6px)';

      setTimeout(() => {
        outSection.classList.remove('active');
        outSection.style.transition = '';
        outSection.style.opacity = '';
        outSection.style.transform = '';
        this._transitioning = false;
      }, this.transitionDuration);
    } else if (outSection) {
      outSection.classList.remove('active');
    }

    // Immediately add .active so DOM state is synchronous (required for tests)
    this._showSection(inSection);
    this._loadTabContent(tabId);
  }

  /** Apply entrance animation to the incoming section */
  _showSection(section) {
    section.style.opacity = '0';
    section.style.transform = 'translateY(6px)';
    section.classList.add('active');

    // Force reflow so the browser registers the initial state before animating
    section.getBoundingClientRect(); // eslint-disable-line

    section.style.transition = `opacity ${this.transitionDuration}ms cubic-bezier(0.4,0,0.2,1), transform ${this.transitionDuration}ms cubic-bezier(0.4,0,0.2,1)`;
    section.style.opacity = '1';
    section.style.transform = 'translateY(0)';

    // Clean up inline styles after transition completes
    setTimeout(() => {
      section.style.transition = '';
      section.style.opacity = '';
      section.style.transform = '';
    }, this.transitionDuration + 20);
  }

  /** Lazy-load content for the activated tab */
  _loadTabContent(tabId) {
    switch (tabId) {
      case 'queue':       loadSHCEQueue();       break;
      case 'errors':      loadSHCEErrors();      break;
      case 'knowledge':   loadSHCEKnowledge();   break;
      case 'history':     loadSHCEHistory();     break;
      case 'environment': loadSHCEEnvironment(); break;
      // 'overview' is loaded via loadSHCEDashboard() / loadOsAdaptationTab()
      // which are triggered by the view-switch handler — no action needed here
    }
  }

  /** Return the currently active tab id */
  getActiveTab() {
    return this.activeTab;
  }

  /** Reset controller state (e.g. when the Control Center view is hidden) */
  reset() {
    this.activeTab = 'overview';
    _shceTabCurrent = 'overview';
    this._transitioning = false;
  }
}

// Singleton instance — shared across the whole frontend
const controlCenterTabs = new ControlCenterTabs();

// ── Tab switching (public API — delegates to ControlCenterTabs) ─────
function switchSHCETab(tab) {
  controlCenterTabs.switchTab(tab);
}

// ── Auto-redirect sequence on execution failure ─────────────────────
function autoNavigateToRepairQueue(queueId) {
  // Step 1: Switch to Logs view
  switchView('logs');
  
  setTimeout(() => {
    // Step 2: Switch to OS Adaptation view and History tab
    switchView('os-adaptation');
    switchSHCETab('history');
    
    setTimeout(() => {
      // Step 3: Switch to Error Monitor tab
      switchSHCETab('errors');
      
      setTimeout(() => {
        // Step 4: Switch to Repair Queue tab
        switchSHCETab('queue');
      }, 250);
    }, 250);
  }, 250);
}
window.autoNavigateToRepairQueue = autoNavigateToRepairQueue;

// ── Main dashboard loader ───────────────────────────────────────────
async function loadSHCEDashboard() {
  try {
    const res = await fetch(`${API}/api/shce/dashboard`);
    const data = await res.json();
    if (!data.ok) return;

    // Update stat tiles
    const status = data.status || {};
    _setSHCETile("shce-core-status",    status.core_active ? "Active" : "Idle",    status.core_active ? "ok" : "warn");
    _setSHCETile("shce-safety-status",  status.safety_ok   ? "All Safe" : "⚠ Alert", status.safety_ok ? "ok" : "warn");
    _setSHCETile("shce-repairs-count",  status.auto_repairs_session ?? 0);
    _setSHCETile("shce-success-rate",   status.success_rate != null ? `${status.success_rate}%` : "—");
    _setSHCETile("shce-queue-depth",    status.queue_depth ?? 0);
    _setSHCETile("shce-kb-size",        (data.knowledge_base || {}).total ?? 0);

    // Queue badge
    const badge = $("shce-queue-badge");
    const qDepth = status.queue_depth ?? 0;
    if (badge) {
      badge.textContent = qDepth;
      badge.dataset.zero = qDepth === 0 ? "1" : "0";
    }

    // Overview panel
    _renderSHCEOverview(data);

    // Also refresh adaptation info (System Info + Progress bars)
    fetchAdaptationStatus(false);

  } catch(err) {
    console.error("[SHCE] Dashboard load error:", err);
  }
}

function _setSHCETile(id, value, cls = "") {
  const el = $(id);
  if (!el) return;
  el.textContent = value;
  el.className = "shce-tile-value" + (cls ? ` ${cls}` : "");
}

function _renderSHCEOverview(data) {
  const el = $("shce-overview-body");
  if (!el) return;
  const env  = data.environment  || {};
  const status = data.status   || {};
  const kb   = data.knowledge_base || {};

  const items = [
    { label: "OS",              value: env.os_label       || env.os_name || "—" },
    { label: "Package Manager", value: env.package_manager || "—" },
    { label: "Network",         value: env.network_online ? "Online" : "Offline",    cls: env.network_online ? "ok" : "warn" },
    { label: "Ollama",          value: env.ollama_running ? "Running" : "Offline",   cls: env.ollama_running ? "ok" : "warn" },
    { label: "Trusted Fixes",   value: kb.trusted         ?? 0 },
    { label: "Experimental",    value: kb.experimental    ?? 0 },
    { label: "Degraded",        value: kb.degraded        ?? 0 },
    { label: "Pending Queue",   value: status.queue_depth ?? 0,                      cls: (status.queue_depth ?? 0) > 0 ? "warn" : "" },
  ];

  el.innerHTML = items.map(item => `
    <div class="shce-overview-item">
      <div class="shce-overview-item-label">${escHtml(item.label)}</div>
      <div class="shce-overview-item-value ${item.cls || ''}">${escHtml(String(item.value))}</div>
    </div>
  `).join("");
}

// ── Queue tab ───────────────────────────────────────────────────────
async function loadSHCEQueue() {
  const container = $("shce-queue-list");
  if (!container) return;
  try {
    const res = await fetch(`${API}/api/shce/queue?limit=50`);
    const data = await res.json();
    const items = (data.queue || []).filter(q => q.status === "pending" || q.status === "executing");

    if (items.length === 0) {
      container.innerHTML = `<div class="shce-empty-row"><svg class="scan-step-svg success" style="width:14px;height:14px;display:inline-block;vertical-align:middle;margin-right:6px;"><use href="#icon-check"></use></svg> Queue is empty — no pending repairs.</div>`;
      return;
    }

    container.innerHTML = items.map(item => {
      const candidates = _parseCandidates(item.candidates);
      const bestCmd = item.selected_candidate || (candidates[0]?.command || "");
      const safety  = candidates[0]?.safety_class || "Safe";
      const safeBg  = safety === "Dangerous" ? "var(--risk-high)" : safety === "Caution" ? "var(--risk-medium)" : "var(--risk-low)";

      return `
      <div class="shce-queue-card" id="shce-qcard-${item.id}">
        <div class="shce-queue-card-header">
          <div class="shce-queue-card-title">⚠ Control Center Repair Candidate #${item.id}</div>
          <span class="shce-status-badge" style="background:${safeBg}22;color:${safeBg};border-color:${safeBg}44">${escHtml(safety)}</span>
        </div>
        <div style="font-size:.8rem;color:var(--text-3);">
          <strong>Triggered by:</strong>
          <code style="display:block;background:rgba(0,0,0,.2);border:1px solid rgba(255,255,255,.06);padding:.35rem .5rem;border-radius:4px;font-size:.75rem;margin-top:.25rem;font-family:var(--mono);white-space:pre-wrap;word-break:break-all;">${escHtml(item.command)}</code>
        </div>
        <div style="font-size:.78rem;color:var(--text-3);margin-top:.15rem;">
          <strong>Error:</strong> ${escHtml((item.error || "").slice(0, 160))}
        </div>
        <div style="margin-top:.5rem;">
          <div style="font-size:.75rem;font-weight:600;color:var(--text-2);margin-bottom:.35rem;">Ranked Candidates:</div>
          <div class="shce-candidate-list">${
            candidates.slice(0, 3).map(c => `
              <div class="shce-candidate-item">
                <span>${escHtml(c.command)}</span>
                <span class="shce-candidate-score">score ${(c.score || 0).toFixed(1)} · ${escHtml(c.source || "")}</span>
              </div>
            `).join("") || '<div class="shce-candidate-item">No candidates generated.</div>'
          }</div>
        </div>
        <div style="margin-top:.5rem;font-size:.75rem;font-weight:600;color:var(--text-2);">
          Selected for execution:
          <textarea id="shce-qcmd-${item.id}" rows="2" style="display:block;width:100%;background:rgba(121,242,192,.06);border:1px solid rgba(121,242,192,.2);padding:.35rem .5rem;border-radius:4px;font-size:.78rem;color:#79f2c0;margin-top:.25rem;font-family:var(--mono);resize:vertical;box-sizing:border-box;">${escHtml(bestCmd)}</textarea>
          <button class="action-btn" style="margin-top:.3rem;padding:.25rem .65rem;font-size:.72rem;" onclick="changeSHCECommand(${item.id})">Change Command</button>
        </div>
        ${safety === "Dangerous" ? `
          <div style="font-size:.75rem;color:#fca5a5;background:rgba(239,68,68,.08);padding:.5rem;border-radius:4px;border:1px solid rgba(239,68,68,.15);">
            ⚠ DANGEROUS: This command modifies system-level settings. Double confirmation required.
          </div>
        ` : ""}
        <div style="font-size:.72rem;color:var(--text-3);">
          Queued: ${escHtml(item.timestamp || "")}
        </div>
        <div class="shce-queue-card-actions">
          ${item.status === 'executing' ? `
            <div class="shce-healing-indicator" style="display:flex;align-items:center;gap:6px;font-size:0.8rem;color:#79f2c0;font-weight:600;padding:.4rem 0;">
              <span class="pulsing-dot" style="width:8px;height:8px;background-color:#79f2c0;border-radius:50%;display:inline-block;box-shadow:0 0 8px #79f2c0;animation:pulse 1.5s infinite ease-in-out;"></span>
              Healing...
            </div>
          ` : `
            <button class="shce-approve-btn" onclick="approveSHCEFix(${item.id}, '${escHtml(safety)}')"><svg class="scan-step-svg success" style="width:12px;height:12px;display:inline-block;vertical-align:middle;margin-right:4px;"><use href="#icon-check"></use></svg> Approve &amp; Run</button>
            <button class="shce-reject-btn"  onclick="rejectSHCEFix(${item.id})">✕ Reject</button>
          `}
        </div>
      </div>`;
    }).join("");
  } catch(err) {
    container.innerHTML = `<div class="shce-empty-row">Failed to load queue: ${escHtml(String(err))}</div>`;
  }
}

async function changeSHCECommand(queueId) {
  const textarea = $(`shce-qcmd-${queueId}`);
  if (!textarea) return;
  const newCmd = textarea.value.trim();
  if (!newCmd) { showToast("Command cannot be empty.", "err"); return; }
  try {
    const res = await fetch(`${API}/api/shce/queue/${queueId}/command`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ command: newCmd }),
    });
    const data = await res.json();
    if (data.ok) {
      showToast("Command updated.", "ok");
      // Cross-tab sync: refresh Error Monitor if it has been loaded so it
      // reflects the new command for the same error entry.
      if (typeof loadSHCEErrors === 'function') loadSHCEErrors();
    } else {
      showToast(`Failed: ${data.detail || "Unknown error"}`, "err");
    }
  } catch(err) {
    showToast(`Error: ${err.message}`, "err");
  }
}
window.changeSHCECommand = changeSHCECommand;

function _parseCandidates(raw) {
  try {
    if (!raw) return [];
    const parsed = JSON.parse(raw);
    return Array.isArray(parsed) ? parsed : [];
  } catch { return []; }
}

async function approveSHCEFix(queueId, safetyClass) {
  if (safetyClass === "Dangerous") {
    const c1 = confirm(`[CRITICAL WARNING] This command is classified as DANGEROUS.\nRunning it may affect OS stability. Proceed?`);
    if (!c1) return;
    const c2 = confirm(`[SECONDARY CONFIRMATION] Are you absolutely certain you want to execute this dangerous fix?`);
    if (!c2) return;
  }
  showToast("Executing Control Center repair…", "ok");
  try {
    const res = await fetch(`${API}/api/shce/approve/${queueId}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ confirm_dangerous: true }),
    });
    const data = await res.json();
    if (data.ok) {
      showToast("✅ Control Center repair executed successfully!", "ok");
      // Auto-replace: if a solution command was found, update tool status cache
      // so Dev Tools refreshes to show the correct state
      toolStatusCache = null;
      if (activeViewName === "devtools") {
        await loadDevToolCards(true);
      }
    } else if (data.requires_secondary_confirmation) {
      showToast("⚠ Dangerous fix requires extra confirmation.", "err");
      return;
    } else {
      showToast(`Repair failed: ${data.stderr || data.error || "Unknown error"}`, "err");
    }
    loadSHCEQueue();
    loadSHCEDashboard();
  } catch(err) {
    showToast(`Error: ${err.message}`, "err");
  }
}

async function rejectSHCEFix(queueId) {
  try {
    const res = await fetch(`${API}/api/shce/reject/${queueId}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ reason: "Rejected by user" }),
    });
    const data = await res.json();
    if (data.ok) showToast("Fix rejected.", "ok");
    loadSHCEQueue();
  } catch(err) {
    showToast(`Error: ${err.message}`, "err");
  }
}

// ── Error Monitor tab ────────────────────────────────────────────────
async function clearResolvedLogs() {
  if (!confirm("Delete all resolved/failed error log entries?")) return;
  try {
    const res = await fetch(`${API}/api/shce/error-log/bulk-resolved`, { method: "DELETE" });
    const data = await res.json();
    if (data.ok) {
      showToast(`Cleared ${data.removed} resolved entries`, "ok");
      loadSHCEErrors();
      loadSHCEDashboard();
    } else {
      showToast(`Failed: ${data.error || "Unknown error"}`, "err");
    }
  } catch(err) {
    showToast(`Error: ${err.message}`, "err");
  }
}
window.clearResolvedLogs = clearResolvedLogs;

async function loadSHCEErrors() {
  const container = $("shce-error-log");
  if (!container) return;

  // Manage the clear button state — button lives in HTML, we just toggle disabled
  const clearBtn = $("shce-clear-resolved-btn");

  try {
    const res  = await fetch(`${API}/api/shce/error-log?limit=30`);
    const data = await res.json();
    const entries = data.entries || [];

    if (clearBtn) {
      clearBtn.disabled = entries.length === 0;
    }

    if (entries.length === 0) {
      container.innerHTML = `<div class="shce-empty-row">No errors captured yet.</div>`;
      return;
    }
    container.innerHTML = entries.map(e => {
      // Use CSS modifier classes for outcome colours — keeps styling in CSS
      // and mirrors the pattern used by Repair Queue's safety-class badges.
      const outcome     = e.outcome || "pending";
      const outcomeIcon = outcome === "resolved" ? `<svg class="scan-step-svg success" style="width:12px;height:12px;display:inline-block;vertical-align:middle;margin-right:4px;"><use href="#icon-check"></use></svg>`
                        : outcome === "failed"   ? "✕" : "⚠";
      const outcomeCls  = `outcome-${outcome}`; // resolved | pending | failed
      const candidates  = _parseCandidates(e.candidates);
      const bestFix     = e.selected_fix || (candidates[0]?.command || "");

      return `
      <div class="shce-queue-card shce-error-card ${outcomeCls}" id="shce-ecard-${e.id}">
        <div class="shce-queue-card-header">
          <div class="shce-queue-card-title ${outcomeCls}">
            ${outcomeIcon} Error Intelligence #${e.id}
          </div>
          <div class="shce-error-card-meta">
            <span class="shce-status-badge ${outcomeCls}">${escHtml(outcome)}</span>
            <span class="shce-card-timestamp">${escHtml(e.timestamp || "")}</span>
      ${outcome !== "pending" ? `<button class="shce-delete-log-btn" onclick="deleteErrorLog(${e.id})" title="Delete this log entry">✕</button>` : `<button class="shce-delete-log-btn" onclick="deleteErrorLog(${e.id})" title="Delete this entry (no candidate found)" style="opacity:0.7">✕</button>`}
          </div>
        </div>
        <div class="shce-error-card-section">
          <div class="shce-error-card-label">Failed command:</div>
          <code class="shce-command-block">$ ${escHtml(e.command || "")}</code>
        </div>
        ${(e.error_raw || "").trim() ? `
        <div class="shce-error-card-section">
          <div class="shce-error-card-label">Error output:</div>
          <div class="shce-error-card-output">${escHtml((e.error_raw || "").slice(0, 240))}</div>
        </div>` : ""}
        ${candidates.length > 0 ? `
        <div class="shce-error-card-section">
          <div class="shce-error-card-label">Candidate fixes (${candidates.length}):</div>
          <div class="shce-candidate-list">
            ${candidates.slice(0, 3).map(c => `
              <div class="shce-candidate-item">
                <span>${escHtml(c.command)}</span>
                <span class="shce-candidate-score">score ${(c.score || 0).toFixed(1)} · ${escHtml(c.source || "")}</span>
              </div>
            `).join("")}
          </div>
        </div>` : ""}
        <div style="margin-top:.5rem;font-size:.75rem;font-weight:600;color:var(--text-2);">
          Proposed Fix command:
          ${outcome === "pending" ? `
            <textarea id="shce-efix-${e.id}" rows="2" style="display:block;width:100%;background:rgba(121,242,192,.06);border:1px solid rgba(121,242,192,.2);padding:.35rem .5rem;border-radius:4px;font-size:.78rem;color:#79f2c0;margin-top:.25rem;font-family:var(--mono);resize:vertical;box-sizing:border-box;" placeholder="No candidates found. Type custom fix command here...">${escHtml(bestFix)}</textarea>
          ` : `
            <code class="shce-command-block" style="color:#79f2c0; display:block; padding:.35rem .5rem; border-radius:4px; margin-top:.25rem;">$ ${escHtml(bestFix || "None")}</code>
          `}
        </div>
        ${outcome === "pending" ? `
        <div class="shce-queue-card-actions">
          <button class="shce-approve-btn" onclick="queueFixFromError(${e.id})">⚡ Queue Fix</button>
        </div>` : ""}
      </div>`;
    }).join("");
  } catch(err) {
    if (clearBtn) clearBtn.disabled = true;
    container.innerHTML = `<div class="shce-empty-row">Failed to load errors: ${escHtml(String(err))}</div>`;
  }
}

async function queueFixFromError(errorId) {
  try {
    const textarea = $("shce-efix-" + errorId);
    const customCmd = textarea ? textarea.value.trim() : "";
    if (!customCmd) {
      showToast("Proposed fix command cannot be empty.", "err");
      return;
    }
    const res = await fetch(`${API}/api/shce/queue-from-error/${errorId}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ custom_command: customCmd })
    });
    const data = await res.json();
    if (data.ok) {
      showToast(data.message || "Fix queued — switch to Repair Queue to approve.", "ok");
      // Refresh Error Monitor so the queued card updates its outcome
      loadSHCEErrors();
      loadSHCEDashboard();
    } else {
      showToast(`Failed: ${data.detail || data.error || "Unknown error"}`, "err");
    }
  } catch(err) {
    showToast(`Error: ${err.message}`, "err");
  }
}
window.queueFixFromError = queueFixFromError;

async function deleteErrorLog(id) {
  if (!confirm(`Are you sure you want to delete error log #${id}?`)) return;
  try {
    const res = await fetch(`${API}/api/shce/error-log/${id}`, {
      method: "DELETE"
    });
    const data = await res.json();
    if (data.ok) {
      showToast("Error log deleted successfully", "ok");
      loadSHCEErrors();
      loadSHCEDashboard();
    } else {
      showToast(`Failed to delete: ${data.error || "Unknown error"}`, "err");
    }
  } catch(err) {
    showToast(`Error: ${err.message}`, "err");
  }
}
window.deleteErrorLog = deleteErrorLog;

async function refreshSHCEPage() {
  const btn = document.querySelector("#view-os-adaptation .btn-refresh-action");
  if (btn) {
    btn.disabled = true;
    setRefreshButtonState(btn, "is-loading");
  }
  
  try {
    // Always reload dashboard tiles regardless of active tab
    await loadSHCEDashboard();
    // Always reload the adaptation overview data
    await loadOsAdaptationTab(true);
    // Reload the currently active tab content
    if (_shceTabCurrent === "queue")       await loadSHCEQueue();
    if (_shceTabCurrent === "errors")      await loadSHCEErrors();
    if (_shceTabCurrent === "knowledge")   await loadSHCEKnowledge();
    if (_shceTabCurrent === "history")     await loadSHCEHistory();
    if (_shceTabCurrent === "environment") await loadSHCEEnvironment();
    
    if (btn) setRefreshButtonState(btn, "is-success");
    showToast("Control Center refreshed.", "ok");
  } catch (err) {
    if (btn) setRefreshButtonState(btn, "is-failure");
    showToast("Refresh failed: " + err.message, "err");
  } finally {
    if (btn) {
      btn.disabled = false;
      setTimeout(() => setRefreshButtonState(btn, ""), 1500);
    }
  }
}
window.refreshSHCEPage = refreshSHCEPage;

// ── Knowledge Base tab ───────────────────────────────────────────────
async function loadSHCEKnowledge() {
  const body = $("shce-kb-body");
  const count = $("shce-kb-count");
  if (!body) return;
  try {
    const res  = await fetch(`${API}/api/shce/knowledge`);
    const data = await res.json();
    _shceKBEntries = data.entries || [];
    if (count) count.textContent = `${_shceKBEntries.length} entries`;
    renderKBTable(_shceKBEntries);
  } catch(err) {
    body.innerHTML = `<tr><td colspan="7" class="shce-empty-row">Load failed: ${escHtml(String(err))}</td></tr>`;
  }
}

function renderKBTable(entries) {
  const body = $("shce-kb-body");
  if (!body) return;
  if (entries.length === 0) {
    body.innerHTML = `<tr><td colspan="7" class="shce-empty-row">No knowledge base entries yet.</td></tr>`;
    return;
  }
  body.innerHTML = entries.map(e => {
    const conf = Math.round((e.confidence_score || 0) * 100);
    const statusCls = (e.verification_status || "").toLowerCase();
    return `
    <tr>
      <td class="mono">${escHtml((e.error_pattern || "").slice(0, 40))}</td>
      <td class="mono">${escHtml((e.successful_fix || "").slice(0, 50))}</td>
      <td>${escHtml(e.os_name || "")}</td>
      <td>
        <div class="shce-conf-bar">
          <div class="shce-conf-track"><div class="shce-conf-fill" style="width:${conf}%"></div></div>
          <span style="font-size:.72rem;color:var(--text-3)">${conf}%</span>
        </div>
      </td>
      <td><span class="shce-status-badge ${statusCls}">${escHtml(e.verification_status || "")}</span></td>
      <td style="color:var(--text-3);font-size:.75rem">${escHtml(e.source || "")}</td>
      <td>
        <button class="shce-reject-btn" style="font-size:.68rem;padding:.2rem .5rem;" onclick="deleteSHCEKBEntry(${e.id})">✕</button>
      </td>
    </tr>`;
  }).join("");
}

function filterKBTable(q) {
  const filtered = q.trim()
    ? _shceKBEntries.filter(e =>
        (e.error_pattern + " " + e.successful_fix + " " + e.os_name + " " + e.source)
          .toLowerCase().includes(q.toLowerCase()))
    : _shceKBEntries;
  const count = $("shce-kb-count");
  if (count) count.textContent = `${filtered.length} entries`;
  renderKBTable(filtered);
}

async function deleteSHCEKBEntry(id) {
  if (!confirm(`Delete knowledge base entry #${id}? This cannot be undone.`)) return;
  try {
    const res = await fetch(`${API}/api/shce/knowledge/${id}`, { method: "DELETE" });
    const data = await res.json();
    if (data.ok) { showToast("Entry deleted.", "ok"); loadSHCEKnowledge(); }
    else showToast(`Failed: ${data.detail || "Unknown error"}`, "err");
  } catch(err) {
    showToast(`Error: ${err.message}`, "err");
  }
}

// ── History tab ──────────────────────────────────────────────────────
async function loadSHCEHistory() {
  const container = $("shce-history-list");
  if (!container) return;

  try {
    const res  = await fetch(`${API}/api/shce/queue?limit=50`);
    const data = await res.json();
    const items = (data.queue || []).filter(q => q.status !== "pending");

    if (items.length === 0) {
      container.innerHTML = `<div class="shce-empty-row">No completed repairs yet.</div>`;
      return;
    }

    const statusIcon = { executed: `<svg class="scan-step-svg success" style="width:12px;height:12px;display:inline-block;vertical-align:middle;margin-right:4px;"><use href="#icon-check"></use></svg>`, rejected: "✕", failed: "⚠", queued: "⚡" };
    const statusCls  = { executed: "outcome-resolved", rejected: "outcome-failed", failed: "outcome-failed", queued: "outcome-pending" };

    const cardHtml = items.map(q => {
      const icon = statusIcon[q.status] || "·";
      const cls  = statusCls[q.status] || "";
      const ts   = (q.timestamp || "").slice(0, 16).replace("T", " ");
      return `
      <div class="shce-queue-card shce-error-card ${cls}" id="shce-hist-${q.id}">
        <div class="shce-queue-card-header">
          <div class="shce-queue-card-title ${cls}">${icon} History #${q.id}</div>
          <div class="shce-error-card-meta">
            <span class="shce-status-badge ${cls}">${escHtml(q.status || "")}</span>
            <span class="shce-card-timestamp">${escHtml(ts)}</span>
            <button class="shce-delete-log-btn" onclick="deleteHistoryItem(${q.id})" title="Delete this history entry">✕</button>
          </div>
        </div>
        <div class="shce-error-card-section">
          <div class="shce-error-card-label">Original command:</div>
          <code class="shce-command-block">$ ${escHtml((q.command||"").slice(0, 160))}</code>
        </div>
        ${(q.selected_candidate || "").trim() ? `
        <div class="shce-error-card-section">
          <div class="shce-error-card-label">Repair applied:</div>
          <code class="shce-command-block" style="color:var(--apple-mint);">$ ${escHtml((q.selected_candidate||"").slice(0, 160))}</code>
        </div>` : ""}
        ${(q.outcome_stderr || q.outcome_stdout || "").trim() ? `
        <div class="shce-error-card-section">
          <div class="shce-error-card-label">Output:</div>
          <div class="shce-error-card-output">${escHtml(((q.outcome_stderr || q.outcome_stdout || "")).slice(0, 200))}</div>
        </div>` : ""}
      </div>`;
    }).join("");

    container.innerHTML = cardHtml;
  } catch(err) {
    container.innerHTML = `<div class="shce-empty-row">Load failed: ${escHtml(String(err))}</div>`;
  }
}

async function deleteHistoryItem(queueId) {
  if (!confirm(`Delete history entry #${queueId}?`)) return;
  try {
    const res = await fetch(`${API}/api/shce/queue/${queueId}`, {
      method: "DELETE"
    });
    const data = await res.json();
    if (data.ok) {
      showToast("History entry deleted.", "ok");
      loadSHCEHistory();
    } else {
      showToast(`Failed: ${data.detail || "Unknown error"}`, "err");
    }
  } catch(err) {
    showToast(`Error: ${err.message}`, "err");
  }
}
window.deleteHistoryItem = deleteHistoryItem;

async function clearAllHistory() {
  if (!confirm("Delete all completed repair history entries? Pending and actively healing items will not be affected.")) return;
  try {
    const res = await fetch(`${API}/api/shce/queue?limit=200`);
    const data = await res.json();
    // Skip pending and executing items — backend blocks those deletions anyway
    const deletable = (data.queue || []).filter(
      q => q.status !== "pending" && q.status !== "executing"
    );
    if (deletable.length === 0) { showToast("No history to clear.", "ok"); return; }
    let removed = 0;
    for (const item of deletable) {
      try {
        const dr = await fetch(`${API}/api/shce/queue/${item.id}`, {
          method: "DELETE"
        });
        if ((await dr.json()).ok) removed++;
      } catch(_) {}
    }
    showToast(`Cleared ${removed} history entries.`, "ok");
    loadSHCEHistory();
    loadSHCEDashboard();
  } catch(err) {
    showToast(`Error clearing history: ${err.message}`, "err");
  }
}
window.clearAllHistory = clearAllHistory;

async function loadSHCEEnvironment() {
  const grid = $("shce-env-grid");
  if (!grid) return;
  grid.textContent = "Loading…";
  try {
    const res  = await fetch(`${API}/api/shce/environment`);
    const data = await res.json();
    const env  = data.environment || {};
    const checkIcon = `<svg class="scan-step-svg success" style="width:12px;height:12px;display:inline-block;vertical-align:middle;margin-right:4px;"><use href="#icon-check"></use></svg>`;
    const cards = [
      { label: "Operating System",  value: env.os_label || env.os_name || "—" },
      { label: "Kernel",            value: env.kernel || "—" },
      { label: "Architecture",      value: env.architecture || "—" },
      { label: "Distribution",      value: env.distro || "—" },
      { label: "Package Manager",   value: env.package_manager || "—" },
      { label: "Python Version",    value: env.python_version || "—" },
      { label: "CPU Cores",         value: env.cpu_count || "—" },
      { label: "Memory",            value: env.memory_gb ? `${env.memory_gb} GB` : "—" },
      { label: "Disk Free",         value: env.disk_free_gb != null ? `${env.disk_free_gb} GB` : "—" },
      { label: "Network",           value: env.network_online ? `${checkIcon} Online` : "⚠ Offline" },
      { label: "Ollama Server",     value: env.ollama_running ? `${checkIcon} Running` : "⚠ Offline" },
      { label: "GPU",               value: env.gpu_info || "Unknown" },
      { label: "Hostname",          value: env.hostname || "—" },
      { label: "Snapshot Time",     value: (env.timestamp || "").replace("T"," ").slice(0,19) },
    ];
    grid.innerHTML = cards.map(c => {
      const isHtml = typeof c.value === "string" && c.value.includes("<svg");
      const displayValue = isHtml ? c.value : escHtml(String(c.value));
      return `
        <div class="shce-env-card">
          <div class="shce-env-card-label">${escHtml(c.label)}</div>
          <div class="shce-env-card-value">${displayValue}</div>
        </div>
      `;
    }).join("");
  } catch(err) {
    grid.innerHTML = `<div class="shce-empty-row">Failed to load environment: ${escHtml(String(err))}</div>`;
  }
}

// ── Background polling (active when SHCE view is open) ──────────────
function startSHCEPolling() {
  stopSHCEPolling();
  _shcePollTimer = setInterval(() => {
    const activeView = document.querySelector(".view.active");
    if (activeView && activeView.id === "view-os-adaptation") {
      loadSHCEDashboard();
      if (_shceTabCurrent === "queue")   loadSHCEQueue();
      if (_shceTabCurrent === "errors")  loadSHCEErrors();
    }
  }, 8000);
}

function stopSHCEPolling() {
  if (_shcePollTimer) { clearInterval(_shcePollTimer); _shcePollTimer = null; }
}

// Expose raw switchView first so the hook can wrap it
window.switchView = switchView;

// Hook into existing view switching to start/stop polling
const _origSwitchView = window.switchView;
window.switchView = function(view, ...args) {
  if (typeof _origSwitchView === "function") _origSwitchView(view, ...args);
  if (view === "os-adaptation") {
    // Ensure the tab controller is in sync with the DOM on each entry
    const activeTab = _shceTabCurrent || 'overview';
    controlCenterTabs.switchTab(activeTab);
    loadSHCEDashboard();
    startSHCEPolling();
  } else {
    stopSHCEPolling();
  }
};

// ── Expose globals ──────────────────────────────────────────────────
window.loadSHCEDashboard    = loadSHCEDashboard;
window.loadSHCEQueue        = loadSHCEQueue;
window.loadSHCEErrors       = loadSHCEErrors;
window.loadSHCEKnowledge    = loadSHCEKnowledge;
window.loadSHCEHistory      = loadSHCEHistory;
window.loadSHCEEnvironment  = loadSHCEEnvironment;
window.switchSHCETab        = switchSHCETab;
window.controlCenterTabs    = controlCenterTabs;
window.approveSHCEFix       = approveSHCEFix;
window.rejectSHCEFix        = rejectSHCEFix;
window.deleteSHCEKBEntry    = deleteSHCEKBEntry;
window.filterKBTable        = filterKBTable;
window.startSHCEPolling     = startSHCEPolling;
window.stopSHCEPolling      = stopSHCEPolling;
window.openOsAdaptationTab  = openOsAdaptationTab;

// Expose modal and drawer control functions for animation hooking
window.openModal               = openModal;
window.closeModal              = closeModal;
window.closeModalBtn           = closeModalBtn;
window.showAgentApprovalModal  = showAgentApprovalModal;
window.confirmAgentCommand     = confirmAgentCommand;
window.closeAgentModal         = closeAgentModal;
window.closeAgentModalBtn      = closeAgentModalBtn;
window.showStartupModal        = showStartupModal;
window.closeStartupModal       = closeStartupModal;
window.closeStartupModalBtn    = closeStartupModalBtn;
window.openSettingsDrawer      = openSettingsDrawer;
window.closeSettingsDrawer     = closeSettingsDrawer;
window.showToast               = showToast;
window.renderAgentCommands     = renderAgentCommands;
window.appendAgentMsg          = appendAgentMsg;
window.appendAgentOutput       = appendAgentOutput;

