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

  // Animate SVG ring gauge fill stroke-dashoffset
  const ringMap = {
    "cpu-ring-val": "cpu-svg-ring",
    "ram-ring-val": "ram-svg-ring",
    "disk-ring-val": "disk-svg-ring",
    "gpu-ring-val": "gpu-svg-ring"
  };
  const svgRing = $(ringMap[valueId]);
  if (svgRing) {
    const circum = 251.2;
    const offset = circum * (1 - clamped / 100);
    svgRing.style.strokeDashoffset = offset.toFixed(1);
  }
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
  $("dashboard-gpu-tile")?.classList.toggle("active", mode === "gpu");

  $("dashboard-cpu-panel")?.classList.toggle("active", mode === "cpu");
  $("dashboard-ram-panel")?.classList.toggle("active", mode === "ram");
  $("dashboard-storage-panel")?.classList.toggle("active", mode === "storage");
  $("dashboard-gpu-panel")?.classList.toggle("active", mode === "gpu");

  if (mode === "storage") {
    if (dashboardRoots.length && !currentFolderPath) {
      loadFolder(dashboardRoots[0].path);
    } else if (!currentFolderPath) {
      loadDashboardDetails().then(() => {
        if (dashboardRoots.length) loadFolder(dashboardRoots[0].path);
      });
    }
  } else if (mode === "gpu") {
    refreshGpuUsage(true);
  } else if (mode === "ram" || mode === "cpu") {
    loadDashboardDetails();
  }
  startMetricsPolling();
}
window.showDashboardMode = showDashboardMode;

async function loadDashboardDetails() {
  const appList = $("linux-app-list");
  const cpuAppList = $("linux-cpu-app-list");

  if (backendState === 'stopping') return;

  try {
    const r = await fetch(`${API}/api/dashboard/resources`);
    if (!r.ok) throw new Error(`HTTP ${r.status}`);
    const d = await r.json();
    dashboardRoots = d.roots || [];
    renderLinuxApps(d.apps || []);
    renderLinuxCpuApps(d.apps || []);
    renderFolderTabs();
    if (!currentFolderPath && dashboardRoots[0]) {
      loadFolder(dashboardRoots[0].path);
    }
  } catch (err) {
    console.warn('[Dashboard] resources fetch fallback:', err.message);
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

  const raw = (apps && apps.length) ? apps : [];
  const userApps = raw.filter(a => a.stoppable !== false).sort((a, b) => {
    const valA = Number(a.memory_percent || a.memory_mb || 0);
    const valB = Number(b.memory_percent || b.memory_mb || 0);
    return valB - valA;
  });
  const osApps = raw.filter(a => a.stoppable === false).sort((a, b) => {
    const valA = Number(a.memory_percent || a.memory_mb || 0);
    const valB = Number(b.memory_percent || b.memory_mb || 0);
    return valB - valA;
  });
  const sorted = [...userApps, ...osApps];

  if (!sorted.length) {
    el.innerHTML = `<div class="empty-row">No active applications currently consuming notable RAM resources.</div>`;
    return;
  }

  el.innerHTML = sorted.map((app, idx) => {
    const memPct = Math.round(Number(app.memory_percent || 0));
    const pids = app.pids || [app.pid || (1000 + idx * 123)];
    const pidVal = pids[0] || 'System';
    const barWidth = Math.min(100, Math.max(5, memPct));
    const isOs = app.stoppable === false;
    const barGradient = isOs ? "linear-gradient(90deg, #7c7c82, #48484a)" : "linear-gradient(90deg, #ffaa00, #ff7139)";
    const badgeBorder = isOs ? "#7c7c82" : "#ffaa00";


    const actionBtn = isOs
      ? `<button class="stop-btn disabled" disabled title="Necessary OS process. Stop is disabled for system safety." style="opacity:0.5;cursor:not-allowed;padding:0.3rem 0.75rem;border-radius:8px;font-size:0.78rem;background:rgba(255,255,255,0.05);border:1px solid rgba(255,255,255,0.1);color:var(--text-3)">Protected</button>`
      : app.browser_control
        ? `<button class="stop-btn browser" onclick="closeOtherBrowserTabs(${escHtml(JSON.stringify(pids))}, ${escHtml(JSON.stringify(app.name || "Browser"))})" style="padding:0.35rem 0.75rem;border-radius:8px;font-size:0.78rem;background:rgba(255,170,0,0.15);border:1px solid rgba(255,170,0,0.4);color:#ffaa00">Close Tabs</button>`
        : `<button class="stop-btn" onclick="stopLinuxApp(${escHtml(JSON.stringify(pids))}, ${escHtml(JSON.stringify(app.name || "App"))})" style="padding:0.35rem 0.85rem;border-radius:8px;font-size:0.78rem;background:rgba(255,55,95,0.15);border:1px solid rgba(255,55,95,0.4);color:#ff375f">Stop</button>`;

    return `
      <div class="app-row-modern ${isOs ? 'os-needed-row' : ''}">
        <div class="app-brand-info">
          ${getAppBrandIcon(app.name)}
          <div>
            <span class="app-brand-name">${escHtml(app.name)}</span>
            ${isOs ? '<span style="font-size:0.7rem;color:var(--text-3);display:block">OS Needed Task</span>' : ''}
          </div>
        </div>
        <div class="app-pid-cell">${pidVal}</div>
        <div class="app-progress-cell">
          <div class="app-progress-fill-bar" style="width: ${barWidth}%; background: ${barGradient};">
            <span class="bar-circular-badge" style="border-color: ${badgeBorder}; color: ${badgeBorder};">${memPct}%</span>
          </div>
        </div>
        <div class="app-pct-cell" style="color: ${badgeBorder}; display:flex; gap:0.6rem; align-items:center; justify-content:flex-end;">
          <span>${app.memory_mb ? `${app.memory_mb} MB (${memPct}%)` : `${memPct}%`}</span>
          ${actionBtn}
        </div>
      </div>
    `;
  }).join("");
}

function getAppBrandIcon(appName) {
  const n = (appName || "").toLowerCase();
  if (n.includes("chrome")) {
    return `<div class="app-brand-icon" style="background:#ea43351a;border:1px solid #ea433540">
      <svg viewBox="0 0 24 24" width="20" height="20"><circle cx="12" cy="12" r="10" fill="#4285F4"/><circle cx="12" cy="12" r="4" fill="#FFFFFF"/><circle cx="12" cy="12" r="3" fill="#EA4335"/></svg>
    </div>`;
  }
  if (n.includes("firefox")) {
    return `<div class="app-brand-icon" style="background:#ff71391a;border:1px solid #ff713940">
      <svg viewBox="0 0 24 24" width="20" height="20"><circle cx="12" cy="12" r="10" fill="#FF7139"/><path d="M12 4a8 8 0 0 1 8 8c0 4.4-3.6 8-8 8" fill="#FFBD2E"/></svg>
    </div>`;
  }
  if (n.includes("code") || n.includes("vscode") || n.includes("visual studio")) {
    return `<div class="app-brand-icon" style="background:#007acc1a;border:1px solid #007acc40">
      <svg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="#007ACC" stroke-width="2.2"><path d="m8 9-4 3 4 3M16 9l4 3-4 3M14 5l-4 14"/></svg>
    </div>`;
  }
  if (n.includes("zoom")) {
    return `<div class="app-brand-icon" style="background:#2d8cff1a;border:1px solid #2d8cff40">
      <svg viewBox="0 0 24 24" width="20" height="20" fill="#2D8CFF"><rect x="3" y="6" width="12" height="12" rx="3"/><path d="M16 10l5-3v10l-5-3v-4z"/></svg>
    </div>`;
  }
  if (n.includes("docker")) {
    return `<div class="app-brand-icon" style="background:#0db7ed1a;border:1px solid #0db7ed40">
      <svg viewBox="0 0 24 24" width="20" height="20" fill="#0DB7ED"><rect x="2" y="10" width="3" height="3" rx="1"/><rect x="6" y="10" width="3" height="3" rx="1"/><rect x="10" y="10" width="3" height="3" rx="1"/><rect x="6" y="6" width="3" height="3" rx="1"/><path d="M2 15c1 3 4 5 10 5s9-2 10-5H2z"/></svg>
    </div>`;
  }
  if (n.includes("node")) {
    return `<div class="app-brand-icon" style="background:#68a0631a;border:1px solid #68a06340">
      <svg viewBox="0 0 24 24" width="20" height="20" fill="#68A063"><path d="M12 2L2 8v8l10 6 10-6V8L12 2z"/></svg>
    </div>`;
  }
  if (n.includes("python")) {
    return `<div class="app-brand-icon" style="background:#3776ab1a;border:1px solid #3776ab40">
      <svg viewBox="0 0 24 24" width="20" height="20" fill="#3776AB"><path d="M12 2A6 6 0 0 0 6 8v2h6v2H4a2 2 0 0 0-2 2v4a6 6 0 0 0 6 6h2v-6H6v-2h8a2 2 0 0 0 2-2V8a6 6 0 0 0-4-6z"/></svg>
    </div>`;
  }
  return `<div class="app-brand-icon" style="background:rgba(0,240,255,0.1);border:1px solid rgba(0,240,255,0.3)">
    <svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="#00f0ff" stroke-width="2"><circle cx="12" cy="12" r="8"/><path d="M12 8v8M8 12h8"/></svg>
  </div>`;
}

function renderLinuxCpuApps(apps) {
  const el = $("linux-cpu-app-list");
  if (!el) return;

  const raw = (apps && apps.length) ? apps : [];
  const userApps = raw.filter(a => a.stoppable !== false).sort((a, b) => {
    const valA = Number(a.cpu_percent || 0);
    const valB = Number(b.cpu_percent || 0);
    return valB - valA;
  });
  const osApps = raw.filter(a => a.stoppable === false).sort((a, b) => {
    const valA = Number(a.cpu_percent || 0);
    const valB = Number(b.cpu_percent || 0);
    return valB - valA;
  });
  const sorted = [...userApps, ...osApps];

  if (!sorted.length) {
    el.innerHTML = `<div class="empty-row">No active applications currently consuming notable CPU resources.</div>`;
    return;
  }

  el.innerHTML = sorted.map((app, idx) => {
    const cpuPct = Math.round(Number(app.cpu_percent || 0));
    const pids = app.pids || [app.pid || (1000 + idx * 123)];
    const pidVal = pids[0] || 'System';
    const barWidth = Math.min(100, Math.max(5, cpuPct));
    const isOs = app.stoppable === false;
    const barGradient = isOs ? "linear-gradient(90deg, #7c7c82, #48484a)" : "linear-gradient(90deg, #00f0ff, #0a84ff)";
    const badgeBorder = isOs ? "#7c7c82" : "#00f0ff";


    const actionBtn = isOs
      ? `<button class="stop-btn disabled" disabled title="Necessary OS process. Stop is disabled for system safety." style="opacity:0.5;cursor:not-allowed;padding:0.3rem 0.75rem;border-radius:8px;font-size:0.78rem;background:rgba(255,255,255,0.05);border:1px solid rgba(255,255,255,0.1);color:var(--text-3)">Protected</button>`
      : app.browser_control
        ? `<button class="stop-btn browser" onclick="closeOtherBrowserTabs(${escHtml(JSON.stringify(pids))}, ${escHtml(JSON.stringify(app.name || "Browser"))})" style="padding:0.35rem 0.75rem;border-radius:8px;font-size:0.78rem;background:rgba(0,240,255,0.15);border:1px solid rgba(0,240,255,0.4);color:#00f0ff">Close Tabs</button>`
        : `<button class="stop-btn" onclick="stopLinuxApp(${escHtml(JSON.stringify(pids))}, ${escHtml(JSON.stringify(app.name || "App"))})" style="padding:0.35rem 0.85rem;border-radius:8px;font-size:0.78rem;background:rgba(255,55,95,0.15);border:1px solid rgba(255,55,95,0.4);color:#ff375f">Stop</button>`;

    return `
      <div class="app-row-modern ${isOs ? 'os-needed-row' : ''}">
        <div class="app-brand-info">
          ${getAppBrandIcon(app.name)}
          <div>
            <span class="app-brand-name">${escHtml(app.name)}</span>
            ${isOs ? '<span style="font-size:0.7rem;color:var(--text-3);display:block">OS Needed Task</span>' : ''}
          </div>
        </div>
        <div class="app-pid-cell">${pidVal}</div>
        <div class="app-progress-cell">
          <div class="app-progress-fill-bar" style="width: ${barWidth}%; background: ${barGradient};">
            <span class="bar-circular-badge" style="border-color: ${badgeBorder}; color: ${badgeBorder};">${cpuPct}%</span>
          </div>
        </div>
        <div class="app-pct-cell" style="color: ${badgeBorder}; display:flex; gap:0.6rem; align-items:center; justify-content:flex-end;">
          <span>${app.cpu_percent !== undefined ? `${app.cpu_percent}% CPU` : `${cpuPct}%`}</span>
          ${actionBtn}
        </div>
      </div>
    `;
  }).join("");
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
      await checkBackend();
      await loadDashboardDetails();
      fetchSystemMetrics();
      fetchAdaptationStatus(false);
      fetchRecipes();
      fetchSystemUpdateCommand(false);
      if (activeViewName !== 'dashboard') {
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

/* ─── DEV TOOLS STORE (Play Store Styled Marketplace) ───── */
const DEV_TOOLS = [
  { icon: "Py", name: "Python",         statusKey: "python3",       hint: "Python missing", description: "High-level programming language for general-purpose programming, data science, and scripting.", category: "languages", popular: true, alltime: true, hot2026: true, offline: true, version: "v3.12+", url: "https://python.org", platforms: ["win", "mac", "linux"] },
  { icon: "Pi", name: "pip",            statusKey: "pip",           hint: "pip broken", description: "The standard package installer for Python libraries and dependencies.", category: "frameworks", popular: true, offline: true, version: "v24.0+", url: "https://pip.pypa.io", platforms: ["win", "mac", "linux"] },
  { icon: "Nd", name: "Node.js",        statusKey: "node",          hint: "Node.js missing", description: "JavaScript runtime environment built on Chrome's V8 engine.", category: "frameworks", popular: true, alltime: true, hot2026: true, offline: true, version: "v20.x LTS", url: "https://nodejs.org", platforms: ["win", "mac", "linux"] },
  { icon: "Nm", name: "npm",            statusKey: "npm",           hint: "npm broken", description: "The default package manager for Node.js to manage project dependencies.", category: "frameworks", popular: true, offline: true, version: "v10.x", url: "https://npmjs.com", platforms: ["win", "mac", "linux"] },
  { icon: "Gt", name: "Git",            statusKey: "git",           hint: "Git missing", description: "Distributed version control system to track software changes across teams.", category: "vcs", popular: true, trending: true, alltime: true, hot2026: true, offline: true, version: "v2.44+", url: "https://git-scm.com", platforms: ["win", "mac", "linux"] },
  { icon: "Dk", name: "Docker",         statusKey: "docker",        hint: "Docker missing", description: "Platform for containerizing, deploying, and running applications in isolated environments.", category: "devops", popular: true, trending: true, alltime: true, hot2026: true, offline: true, version: "v26.0+", url: "https://docker.com", platforms: ["win", "mac", "linux"] },
  { icon: "Vs", name: "VS Code",        statusKey: "code",          hint: "VS Code corrupted installation", description: "Extensible, lightweight source-code editor developed by Microsoft.", category: "ides", popular: true, trending: true, alltime: true, hot2026: true, offline: true, version: "v1.88+", url: "https://code.visualstudio.com", platforms: ["win", "mac", "linux"] },
  { icon: "Jv", name: "Java",           statusKey: "java",          hint: "Java missing", description: "Object-oriented, class-based programming language for enterprise cross-platform apps.", category: "languages", popular: true, alltime: true, offline: true, version: "JDK 21 LTS", url: "https://java.com", platforms: ["win", "mac", "linux"] },
  { icon: "Sn", name: "Snap",           statusKey: "snap",          hint: "snap missing", description: "App package management system for Linux desktop, cloud, and IoT.", category: "devops", offline: true, version: "v2.61+", url: "https://snapcraft.io", platforms: ["linux"] },
  { icon: "As", name: "Android Studio", statusKey: "android",       hint: "Android Studio missing", description: "Official Integrated Development Environment (IDE) for Android app development.", category: "ides", popular: true, offline: true, version: "v2024.1+", url: "https://developer.android.com/studio", platforms: ["win", "mac", "linux"] },
  { icon: "Ol", name: "Ollama",         statusKey: "ollama",        hint: "Ollama missing", description: "Lightweight tool to run, build, and manage large language models locally.", category: "devops", trending: true, hot2026: true, offline: true, version: "v0.1.30+", url: "https://ollama.com", platforms: ["win", "mac", "linux"] },
  { icon: "Po", name: "Poetry",         statusKey: "poetry",        hint: "Poetry missing", description: "Python packaging and dependency management tool.", category: "frameworks", hot2026: true, offline: true, version: "v1.8+", url: "https://python-poetry.org", platforms: ["win", "mac", "linux"] },
  { icon: "Pn", name: "pnpm",           statusKey: "pnpm",          hint: "pnpm missing", description: "Fast, disk space efficient package manager for Node.js.", category: "frameworks", trending: true, hot2026: true, offline: true, version: "v9.0+", url: "https://pnpm.io", platforms: ["win", "mac", "linux"] },
  { icon: "Rs", name: "Rust",           statusKey: "rust",          hint: "Rust compiler missing", description: "Modern systems programming language focused on safety, speed, and concurrency.", category: "languages", trending: true, hot2026: true, offline: true, version: "v1.77+", url: "https://rust-lang.org", platforms: ["win", "mac", "linux"] },
  { icon: "Go", name: "Go",             statusKey: "go",            hint: "Go missing", description: "Statically typed, compiled programming language designed at Google for backend scalability.", category: "languages", popular: true, hot2026: true, offline: true, version: "v1.22+", url: "https://golang.org", platforms: ["win", "mac", "linux"] },
  { icon: "Ht", name: "htop",           statusKey: "htop",          hint: "htop missing", description: "Interactive system-monitor, process-viewer, and process-manager for terminal.", category: "cli", offline: true, version: "v3.3+", url: "https://htop.dev", platforms: ["mac", "linux"] },
  { icon: "Nv", name: "Neovim",         statusKey: "neovim",        hint: "Neovim missing", description: "Hyperextensible, Vim-based text editor for high-efficiency editing.", category: "ides", trending: true, hot2026: true, offline: true, version: "v0.10+", url: "https://neovim.io", platforms: ["win", "mac", "linux"] },
  { icon: "Gh", name: "GitHub CLI",     statusKey: "gh",            hint: "GitHub CLI missing", description: "Official command-line interface to interact with GitHub issues, PRs, and repos.", category: "cli", trending: true, offline: true, version: "v2.45+", url: "https://cli.github.com", platforms: ["win", "mac", "linux"] },
  { icon: "Fz", name: "fzf",            statusKey: "fzf",           hint: "fzf missing", description: "General-purpose command-line fuzzy finder.", category: "cli", offline: true, version: "v0.48+", url: "https://github.com/junegunn/fzf", platforms: ["win", "mac", "linux"] },
  { icon: "Jq", name: "jq",             statusKey: "jq",            hint: "jq missing", description: "Command-line JSON processor to slice, filter, map, and transform JSON data.", category: "cli", offline: true, version: "v1.7+", url: "https://jqlang.github.io/jq", platforms: ["win", "mac", "linux"] },
  { icon: "Tx", name: "tmux",           statusKey: "tmux",          hint: "tmux missing", description: "Terminal multiplexer to manage multiple terminal sessions in a single window.", category: "cli", offline: true, version: "v3.4+", url: "https://github.com/tmux/tmux", platforms: ["mac", "linux"] },
  { icon: "Pc", name: "PyCharm",        statusKey: "pycharm",       hint: "PyCharm missing", description: "Feature-rich IDE for Python development by JetBrains.", category: "ides", popular: true, offline: true, version: "v2024.1", url: "https://jetbrains.com/pycharm", platforms: ["win", "mac", "linux"] },
  { icon: "St", name: "Sublime",        statusKey: "sublime",       hint: "Sublime Text missing", description: "Sophisticated, fast text editor for code, markup, and prose.", category: "ides", offline: true, version: "Text 4", url: "https://sublimetext.com", platforms: ["win", "mac", "linux"] },
  { icon: "Pm", name: "Postman",        statusKey: "postman",       hint: "Postman missing", description: "API platform for building, testing, and managing APIs.", category: "testing", popular: true, version: "v10.x", url: "https://postman.com", platforms: ["win", "mac", "linux"] },
  { icon: "Db", name: "DBeaver CE",     statusKey: "dbeaver",       hint: "DBeaver CE missing", description: "Free universal database tool and SQL client supporting SQL databases.", category: "databases", popular: true, offline: true, version: "v24.0+", url: "https://dbeaver.io", platforms: ["win", "mac", "linux"] },
  { icon: "Sl", name: "Slack",          statusKey: "slack",         hint: "Slack missing", description: "Team communication and collaboration software application.", category: "cli", popular: true, version: "v4.37+", url: "https://slack.com", platforms: ["win", "mac", "linux"] },
  { icon: "Br", name: "Brave",          statusKey: "brave",         hint: "Brave missing", description: "Privacy-focused web browser that blocks trackers and ads by default.", category: "testing", popular: true, offline: true, version: "v1.64+", url: "https://brave.com", platforms: ["win", "mac", "linux"] },
  { icon: "Ch", name: "Chrome",         statusKey: "chrome",        hint: "Chrome missing", description: "Fast, secure, and popular web browser developed by Google.", category: "testing", popular: true, alltime: true, offline: true, version: "v123+", url: "https://google.com/chrome", platforms: ["win", "mac", "linux"] },
  { icon: "Ff", name: "Firefox",        statusKey: "firefox",       hint: "Firefox missing", description: "Free, open-source web browser developed by Mozilla.", category: "testing", popular: true, offline: true, version: "v124+", url: "https://mozilla.org/firefox", platforms: ["win", "mac", "linux"] },
];

let currentDevToolsCategory = "all";

function filterDevToolsCategory(category) {
  currentDevToolsCategory = category;
  const pills = document.querySelectorAll("#devtools-category-nav .category-pill");
  pills.forEach(pill => {
    const text = pill.textContent.toLowerCase();
    const isActive = (category === "all" && text === "all") ||
      (category === "popular" && text === "popular") ||
      (category === "trending" && text.includes("trending")) ||
      (category === "alltime" && text.includes("all-time")) ||
      (category === "hot2026" && text.includes("2026")) ||
      (category === "offline" && text.includes("offline")) ||
      (category === "languages" && text === "languages") ||
      (category === "frameworks" && text === "frameworks") ||
      (category === "databases" && text === "databases") ||
      (category === "devops" && text === "devops") ||
      (category === "ides" && text.includes("ides")) ||
      (category === "vcs" && text.includes("git")) ||
      (category === "cli" && text.includes("cli")) ||
      (category === "testing" && text.includes("testing"));
    pill.classList.toggle("active", isActive);
  });
  searchDevTools();
}

function clearDevToolsSearch() {
  const input = $("devtools-search");
  if (input) input.value = "";
  filterDevToolsCategory("all");
}

function renderStoreHero(tool, installed) {
  const container = $("devtools-hero-container");
  if (!container || !tool) return;

  const isInstalled = installed === true;
  const statusBadge = isInstalled
    ? `<span class="store-badge installed">Installed</span>`
    : `<span class="store-badge missing">Not Found</span>`;

  const btnText = isInstalled ? "Manage Tool" : "Install Tool";
  const btnClass = isInstalled ? "secondary-btn" : "primary-btn hero-btn";

  container.innerHTML = `
    <div class="store-hero-card" onclick="openDevToolProductModal('${escHtml(tool.name)}')">
      <div class="hero-icon-box">${escHtml(tool.icon)}</div>
      <div class="hero-content">
        <div class="hero-badge-row">
          <span class="hero-tag">FEATURED DEVELOPER TOOL</span>
          ${statusBadge}
        </div>
        <h2 class="hero-title">${escHtml(tool.name)}</h2>
        <p class="hero-desc">${escHtml(tool.description)}</p>
        <div class="hero-platforms">
          <span class="platform-chip supported">Windows</span>
          <span class="platform-chip supported">macOS</span>
          <span class="platform-chip supported">Linux</span>
          <span class="platform-chip" style="margin-left:0.5rem; color:var(--text-3); font-weight:600;">${escHtml(tool.version || 'v26.0+')}</span>
        </div>
      </div>
      <div class="hero-action-box">
        <button class="${btnClass}" onclick="event.stopPropagation(); openDevToolManager('${escHtml(tool.name)}', ${isInstalled})">
          ${btnText}
        </button>
      </div>
    </div>
  `;
}

function renderStoreToolCard(tool, installed) {
  const isInstalled = installed === true;
  
  const statusBadge = isInstalled
    ? `<span class="store-badge installed">Installed</span>`
    : `<span class="store-badge missing">Not Found</span>`;

  const trendingBadge = tool.trending ? `<span class="store-badge trending">Trending</span>` : "";
  const offlineBadge = tool.offline ? `<span class="store-badge offline">Offline Ready</span>` : "";
  const hot2026Badge = tool.hot2026 ? `<span class="store-badge hot2026">2026 Hot</span>` : "";

  const actionBtnClass = isInstalled ? "tool-action-btn btn-installed" : "tool-action-btn btn-install";
  const actionBtnText = isInstalled ? "Installed" : "Fix / Install";

  const platforms = tool.platforms || ["win", "mac", "linux"];
  const platformChips = platforms.map(p => {
    const label = p === "win" ? "Win" : p === "mac" ? "Mac" : "Linux";
    return `<span style="color:var(--text-3); font-weight:500;">${label}</span>`;
  }).join(" · ");

  return `
    <div class="store-tool-card" data-tool-name="${escHtml(tool.name)}" data-tool-category="${escHtml(tool.category || '')}" data-installed="${isInstalled}" onclick="openDevToolProductModal('${escHtml(tool.name)}')">
      <div>
        <div class="tool-card-top">
          <div class="tool-card-icon">${escHtml(tool.icon)}</div>
          <div class="tool-card-header-text">
            <h3 class="tool-card-name">${escHtml(tool.name)}</h3>
            <span class="tool-card-category-pill">${escHtml(tool.category || 'Developer Tool')}</span>
          </div>
        </div>
        <p class="tool-card-desc">${escHtml(tool.description || '')}</p>
      </div>

      <div>
        <div class="tool-card-meta-row">
          <div class="tool-card-badges">
            ${statusBadge}
            ${trendingBadge}
            ${hot2026Badge}
            ${offlineBadge}
          </div>
        </div>

        <div class="tool-card-footer">
          <div class="tool-card-platforms">
            ${platformChips}
          </div>
          <button class="${actionBtnClass}" onclick="event.stopPropagation(); openDevToolManager('${escHtml(tool.name)}', ${isInstalled})">
            ${actionBtnText}
          </button>
        </div>
      </div>
    </div>
  `;
}

function renderDevToolsStoreSections(toolStatus) {
  const sectionsWrapper = $("devtools-store-sections");
  if (!sectionsWrapper) return;

  sectionsWrapper.innerHTML = "";

  // Helper to map tools with status
  const mappedTools = DEV_TOOLS.map(tool => ({
    tool,
    installed: tool.statusKey ? (toolStatus[tool.statusKey] === true) : false
  }));

  // Store Curated Definitions
  const curatedSections = [
    {
      id: "popular",
      title: "Popular Developer Tools",
      subtitle: "Most requested runtimes, compilers, and desktop developer tools.",
      tools: mappedTools.filter(m => m.tool.popular)
    },
    {
      id: "trending",
      title: "Trending Now",
      subtitle: "Tools gaining high developer adoption across OS environments.",
      tools: mappedTools.filter(m => m.tool.trending)
    },
    {
      id: "alltime",
      title: "All-Time Best Tools",
      subtitle: "Foundational developer suites required on every workstation.",
      tools: mappedTools.filter(m => m.tool.alltime)
    },
    {
      id: "hot2026",
      title: "2026 Hot Developer Tools",
      subtitle: "Modern AI coding tools, next-gen runtimes, and local AI engines.",
      tools: mappedTools.filter(m => m.tool.hot2026)
    },
    {
      id: "offline",
      title: "Offline Developer Tools",
      subtitle: "Tools that work locally without requiring an active internet connection after installation.",
      tools: mappedTools.filter(m => m.tool.offline)
    },
    {
      id: "languages",
      title: "Programming Languages & Compilers",
      subtitle: "Python, Java, Rust, Go, and core language runtimes.",
      tools: mappedTools.filter(m => m.tool.category === "languages")
    },
    {
      id: "frameworks",
      title: "Package Managers & Frameworks",
      subtitle: "Node.js, npm, pip, pnpm, Poetry, and ecosystem dependencies.",
      tools: mappedTools.filter(m => m.tool.category === "frameworks")
    },
    {
      id: "devops",
      title: "DevOps & Containerization",
      subtitle: "Docker, Ollama, Snap, and orchestration utilities.",
      tools: mappedTools.filter(m => m.tool.category === "devops")
    },
    {
      id: "ides",
      title: "IDEs & Code Editors",
      subtitle: "VS Code, Android Studio, PyCharm, Neovim, and Sublime.",
      tools: mappedTools.filter(m => m.tool.category === "ides")
    },
    {
      id: "cli",
      title: "CLI Tools & Terminal Utilities",
      subtitle: "GitHub CLI, fzf, jq, tmux, htop, and power terminal utilities.",
      tools: mappedTools.filter(m => m.tool.category === "cli")
    },
    {
      id: "testing",
      title: "Testing, APIs & Security",
      subtitle: "Postman, DBeaver, Brave, Chrome, and API testing suites.",
      tools: mappedTools.filter(m => m.tool.category === "testing" || m.tool.category === "databases")
    }
  ];

  curatedSections.forEach(sec => {
    if (!sec.tools || sec.tools.length === 0) return;

    const secEl = document.createElement("div");
    secEl.className = "store-section";
    secEl.id = `section-${sec.id}`;

    secEl.innerHTML = `
      <div class="store-section-header">
        <div>
          <div class="store-section-title-box">
            <h2 class="store-section-title">${escHtml(sec.title)}</h2>
          </div>
          <div class="store-section-desc">${escHtml(sec.subtitle)}</div>
        </div>
      </div>
      <div class="store-grid">
        ${sec.tools.slice(0, 8).map(m => renderStoreToolCard(m.tool, m.installed)).join("")}
      </div>
    `;

    sectionsWrapper.appendChild(secEl);
  });
}

async function refreshDevToolsPage() {
  const btn = $("btn-devtools-refresh");
  setRefreshButtonState(btn, "is-loading");
  await runGlobalAdaptationRefresh("devtools");
  toolStatusCache = null;
  await loadDevToolCards(true);
  setRefreshButtonState(btn, "is-success");
  showToast("Developer tools store refreshed.", "ok");
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

let managedAppsLoadedCache = false;

async function loadDevToolCards(force = false) {
  const heroContainer = $("devtools-hero-container");
  const sectionsWrapper = $("devtools-store-sections");
  const grid = $("devtools-grid");

  // Instant load when cached
  if (!force && toolStatusCache && Object.keys(toolStatusCache).length > 0) {
    const heroTool = DEV_TOOLS.find(t => t.name === "Docker") || DEV_TOOLS[0];
    const heroInstalled = heroTool.statusKey ? (toolStatusCache[heroTool.statusKey] === true) : false;
    renderStoreHero(heroTool, heroInstalled);
    renderDevToolsStoreSections(toolStatusCache);
    searchDevTools();

    // Silently refresh in background
    getToolStatus(false).then(updatedStatus => {
      if (updatedStatus && Object.keys(updatedStatus).length > 0) {
        const hInstalled = heroTool.statusKey ? (updatedStatus[heroTool.statusKey] === true) : false;
        renderStoreHero(heroTool, hInstalled);
        renderDevToolsStoreSections(updatedStatus);
      }
    }).catch(() => {});
    return;
  }

  // Show skeleton loading state only on initial load
  if (sectionsWrapper && !toolStatusCache) {
    sectionsWrapper.innerHTML = `
      <div class="store-grid">
        ${[1,2,3,4].map(() => `
          <div class="skeleton-card">
            <div class="skeleton-shimmer"></div>
            <div style="display:flex;gap:0.8rem;">
              <div class="skeleton-block" style="width:48px;height:48px;"></div>
              <div style="flex:1;">
                <div class="skeleton-block" style="width:60%;height:16px;margin-bottom:8px;"></div>
                <div class="skeleton-block" style="width:40%;height:12px;"></div>
              </div>
            </div>
            <div class="skeleton-block" style="width:100%;height:32px;margin-top:12px;"></div>
          </div>
        `).join("")}
      </div>
    `;
  }

  // Fetch dynamically managed tools
  if (!managedAppsLoadedCache || force) {
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
              category: "devops",
              popular: false,
              offline: true,
              version: "Latest",
              platforms: ["win", "mac", "linux"]
            };
            DEV_TOOLS.push(existing);
          }
          if (app.uninstall_command) {
            existing.uninstall_command = app.uninstall_command;
          }
        });
        managedAppsLoadedCache = true;
      }
    } catch (err) {
      console.error("[DevTools] Failed to load managed apps:", err);
    }
  }

  let toolStatus = {};
  let fetchError = null;
  try {
    if (force) toolStatusCache = null;
    toolStatus = await getToolStatus(force);
  } catch (err) {
    fetchError = err;
  }

  // Handle backend error state
  if (fetchError && (!toolStatus || Object.keys(toolStatus).length === 0)) {
    if (sectionsWrapper) {
      sectionsWrapper.innerHTML = `
        <div class="store-error-state">
          <h3 class="empty-title">Unable to load developer tools store</h3>
          <p class="empty-desc">Could not connect to system backend service. Check if PC Doctor service is running.</p>
          <button class="primary-btn" onclick="loadDevToolCards(true)">Retry Loading</button>
        </div>
      `;
    }
    return;
  }

  // Pick Featured Tool (Docker or VS Code or Python)
  const heroTool = DEV_TOOLS.find(t => t.name === "Docker") || DEV_TOOLS[0];
  const heroInstalled = heroTool.statusKey ? (toolStatus[heroTool.statusKey] === true) : false;
  renderStoreHero(heroTool, heroInstalled);

  // Render Curated Sections
  renderDevToolsStoreSections(toolStatus);

  // Apply active search/filter state
  searchDevTools();
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
        riskBadge.className = `store-badge ${d.risk === "High" ? "missing" : d.risk === "Medium" ? "trending" : "installed"}`;
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
  const searchInput = $("devtools-search");
  const query = (searchInput?.value || "").toLowerCase().trim();
  const clearBtn = $("devtools-search-clear");
  
  if (clearBtn) {
    clearBtn.classList.toggle("hidden", query.length === 0);
  }

  const heroContainer = $("devtools-hero-container");
  const storeSections = $("devtools-store-sections");
  const searchStatus = $("devtools-search-status");
  const grid = $("devtools-grid");
  const searchTitle = $("devtools-search-title");
  const searchCount = $("devtools-search-count");

  const cat = currentDevToolsCategory || "all";
  const isDefaultView = query === "" && cat === "all";

  if (isDefaultView) {
    if (heroContainer) heroContainer.classList.remove("hidden");
    if (storeSections) storeSections.classList.remove("hidden");
    if (searchStatus) searchStatus.classList.add("hidden");
    if (grid) grid.classList.add("hidden");
    return;
  }

  // Filtered view mode active
  if (heroContainer) heroContainer.classList.add("hidden");
  if (storeSections) storeSections.classList.add("hidden");
  if (searchStatus) searchStatus.classList.remove("hidden");
  if (grid) grid.classList.remove("hidden");

  // Get current tool status cache
  const toolStatus = toolStatusCache || {};

  // Filter DEV_TOOLS memory registry
  const filtered = DEV_TOOLS.filter(tool => {
    const matchesQuery = query === "" || 
      tool.name.toLowerCase().includes(query) ||
      (tool.description || "").toLowerCase().includes(query) ||
      (tool.category || "").toLowerCase().includes(query) ||
      (tool.hint || "").toLowerCase().includes(query);

    if (!matchesQuery) return false;

    if (cat === "all") return true;
    if (cat === "popular") return tool.popular;
    if (cat === "trending") return tool.trending;
    if (cat === "alltime") return tool.alltime;
    if (cat === "hot2026") return tool.hot2026;
    if (cat === "offline") return tool.offline;
    return (tool.category || "").toLowerCase() === cat;
  });

  // Update status header title
  if (searchTitle) {
    if (query) {
      searchTitle.innerHTML = `Search results for "<span style="color:var(--apple-cyan)">${escHtml(query)}</span>"`;
    } else {
      const catNames = {
        popular: "Popular Developer Tools",
        trending: "🔥 Trending Tools",
        alltime: "⭐ All-Time Best Tools",
        hot2026: "⚡ 2026 Hot Tools",
        offline: "📴 Offline Developer Tools",
        languages: "Programming Languages",
        frameworks: "Package Managers & Frameworks",
        databases: "Databases & SQL Tools",
        devops: "DevOps & Containers",
        ides: "IDEs & Code Editors",
        vcs: "Git & Version Control",
        cli: "CLI Tools & Terminal Utilities",
        testing: "Testing & Security Tools"
      };
      searchTitle.textContent = catNames[cat] || "Filtered Tools";
    }
  }

  if (searchCount) {
    searchCount.textContent = `${filtered.length} tool${filtered.length === 1 ? '' : 's'} found`;
  }

  grid.innerHTML = "";


  // ── Live Package Search Panel ────────────────────────────────────────────
  if (query) {
    const searchPanel = document.createElement("div");
    searchPanel.id = "pkg-search-panel";
    searchPanel.style.cssText = "grid-column:1/-1; margin-bottom:1.25rem;";
    searchPanel.innerHTML = `
      <div style="display:flex;align-items:center;gap:.6rem;margin-bottom:.75rem;">
        <div class="tool-card-icon" style="background:rgba(56,189,248,0.12);color:#38bdf8;flex-shrink:0;">?</div>
        <div>
          <h3 style="margin:0;font-size:1rem;font-weight:700;color:var(--text-1);">
            Live Package Search — <span style="color:#38bdf8;">${escHtml(query)}</span>
          </h3>
          <span style="font-size:.78rem;color:var(--text-3);">
            Searching winget, apt, snap, brew, npm, PyPI...
          </span>
        </div>
        <div id="pkg-search-spinner" style="margin-left:auto;width:18px;height:18px;border:2px solid rgba(255,255,255,0.1);border-top-color:#38bdf8;border-radius:50%;animation:spin 0.7s linear infinite;flex-shrink:0;"></div>
      </div>
      <div id="pkg-search-results" style="display:flex;flex-direction:column;gap:.45rem;"></div>
      <div id="pkg-search-empty" style="display:none;padding:1.2rem;background:rgba(15,20,35,0.6);border-radius:10px;border:1px solid rgba(255,255,255,0.06);">
        <p style="margin:0 0 .6rem;color:var(--text-2);font-size:.88rem;">
          No packages found in any registry for <strong>${escHtml(query)}</strong>.
          Enter a command manually:
        </p>
        <div style="display:flex;gap:.5rem;">
          <input id="pkg-manual-cmd" type="text" placeholder="e.g. winget install MyApp" style="flex:1;background:rgba(0,0,0,0.4);border:1px solid rgba(255,255,255,0.12);border-radius:7px;padding:.45rem .75rem;color:var(--text-1);font-family:var(--font-mono);font-size:.8rem;outline:none;" />
          <button class="primary-btn" style="padding:.42rem 1rem;font-size:.82rem;" onclick="installManualPkgCmd()">Run</button>
        </div>
      </div>
    `;
    grid.appendChild(searchPanel);

    // Trigger live search
    if (dynamicSearchTimeout) clearTimeout(dynamicSearchTimeout);
    dynamicSearchTimeout = setTimeout(() => runLivePkgSearch(query), 280);
  }

  if (filtered.length === 0 && !query) {
    grid.innerHTML = `
      <div class="store-empty-state">
        <div class="empty-icon">?</div>
        <h3 class="empty-title">No tools found in this category</h3>
        <p class="empty-desc">Try selecting another category or searching for developer tools above.</p>
        <button class="primary-btn" onclick="filterDevToolsCategory('all')">View All Developer Tools</button>
      </div>
    `;
    return;
  }

  // Render matching tool cards from DEV_TOOLS registry
  filtered.forEach(tool => {
    const installed = tool.statusKey ? (toolStatus[tool.statusKey] === true) : false;
    grid.insertAdjacentHTML("beforeend", renderStoreToolCard(tool, installed));
  });
}

// ── Live Package Search — calls /api/devtools/search-packages ─────────────
// ── Resolution pipeline state (per-search context) ────────────────────────
let _lastResolveQuery    = "";
let _lastResolveVariant  = "";
let _lastResolveSelected = null;   // ResolutionCandidate | null

// ── Call /api/devtools/resolve — full pipeline ────────────────────────────
async function runLivePkgSearch(query) {
  const spinner   = document.getElementById("pkg-search-spinner");
  const resultsEl = document.getElementById("pkg-search-results");
  const emptyEl   = document.getElementById("pkg-search-empty");
  if (!resultsEl) return;

  _lastResolveQuery   = query;
  _lastResolveVariant = "";

  try {
    const res  = await fetch("/api/devtools/resolve", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ query, variant: "", force_refresh: false }),
    });
    const data = await res.json();
    if (spinner) spinner.style.display = "none";

    if (!data.ok || data.status === "not_found" || !data.candidates?.length) {
      if (emptyEl) emptyEl.style.display = "block";
      return;
    }

    resultsEl.innerHTML = "";

    if (data.status === "auto_selected" && data.selected) {
      // High-confidence result — show it prominently at the top
      _lastResolveSelected = data.selected;
      resultsEl.insertAdjacentHTML("beforeend",
        renderPkgResultRow(data.selected, data.confidence, true, data.from_cache));
      // Show remaining candidates (lower confidence) below
      data.candidates
        .filter(c => c.pkg_id !== data.selected.pkg_id)
        .slice(0, 5)
        .forEach(c => resultsEl.insertAdjacentHTML("beforeend",
          renderPkgResultRow(c, c.total_score, false, false)));
    } else {
      // needs_disambiguation — show a disambiguation header + all candidates
      resultsEl.insertAdjacentHTML("beforeend", renderDisambiguationHeader(query, data.confidence));
      data.candidates.slice(0, 8).forEach(c =>
        resultsEl.insertAdjacentHTML("beforeend",
          renderPkgResultRow(c, c.total_score, false, false)));
    }

  } catch (err) {
    if (spinner) spinner.style.display = "none";
    if (emptyEl) emptyEl.style.display = "block";
    console.error("resolve error", err);
  }
}

// ── Disambiguation header (shown when confidence < 80%) ───────────────────
function renderDisambiguationHeader(query, topScore) {
  return `
    <div style="
        padding:.75rem 1rem;margin-bottom:.25rem;
        background:rgba(245,158,11,0.07);
        border:1px solid rgba(245,158,11,0.22);
        border-radius:10px;
        display:flex;align-items:center;gap:.65rem;
      ">
      <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="#f59e0b"
           stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="flex-shrink:0;">
        <path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"/>
        <line x1="12" y1="9" x2="12" y2="13"/><line x1="12" y1="17" x2="12.01" y2="17"/>
      </svg>
      <div>
        <div style="font-size:.85rem;font-weight:700;color:#f59e0b;">
          Multiple matches — select the correct one
        </div>
        <div style="font-size:.75rem;color:var(--text-3);">
          Best match confidence: ${topScore.toFixed(0)}% — below the 80% auto-select threshold.
          Review the candidates below or enter an ID manually.
        </div>
      </div>
    </div>
  `;
}

// ── Render one result row with confidence bar + verification badge ─────────
function renderPkgResultRow(r, confidence, isTopPick, fromCache) {
  const managerColor = {
    winget:"#38bdf8", msstore:"#60a5fa", apt:"#4ade80",
    snap:"#f59e0b",   flatpak:"#a78bfa", brew:"#fb923c",
    npm:"#f87171",    pip:"#fbbf24",     choco:"#c084fc",
    scoop:"#94a3b8",
  }[r.manager] || "#94a3b8";

  const score = confidence ?? r.total_score ?? 0;
  const barColor = score >= 80 ? "#4ade80" : score >= 60 ? "#f59e0b" : "#f87171";

  // Verification badge
  let verBadge = "";
  if (r.verified === true) {
    verBadge = `<span style="padding:.15rem .5rem;border-radius:4px;font-size:.65rem;font-weight:700;background:rgba(74,222,128,0.12);color:#4ade80;border:1px solid rgba(74,222,128,0.25);">Verified</span>`;
  } else if (r.verified === false) {
    verBadge = `<span style="padding:.15rem .5rem;border-radius:4px;font-size:.65rem;font-weight:700;background:rgba(239,68,68,0.12);color:#f87171;border:1px solid rgba(239,68,68,0.25);">Unverified</span>`;
  } else {
    verBadge = `<span style="padding:.15rem .5rem;border-radius:4px;font-size:.65rem;color:var(--text-3);background:rgba(255,255,255,0.05);border:1px solid rgba(255,255,255,0.1);">Unknown</span>`;
  }

  // Cache badge
  const cacheBadge = fromCache
    ? `<span style="padding:.15rem .5rem;border-radius:4px;font-size:.65rem;font-weight:700;background:rgba(56,189,248,0.1);color:#38bdf8;border:1px solid rgba(56,189,248,0.2);">Verified &middot; cached</span>`
    : "";

  // Top-pick glow border
  const border = isTopPick
    ? "border:1px solid rgba(74,222,128,0.35)"
    : "border:1px solid rgba(255,255,255,0.07)";

  const abbr = (r.name || r.pkg_id || r.id || "?").slice(0, 2).toUpperCase();
  const pkgId = r.pkg_id || r.id;
  const name  = r.name || pkgId;
  const desc  = r.description
    ? escHtml(r.description.slice(0, 90)) + (r.description.length > 90 ? "…" : "")
    : "";
  const pub   = r.publisher
    ? `<span style="font-size:.73rem;color:var(--text-3);">${escHtml(r.publisher)}</span> &middot; `
    : "";
  const ver   = r.version
    ? `<span style="font-size:.73rem;color:var(--text-3);">${escHtml(r.version)}</span>`
    : "";

  // Encode for onclick attribute
  const safeId      = escHtml(pkgId);
  const safeMgr     = escHtml(r.manager);
  const safeName    = escHtml(name);
  const safeSrc     = escHtml(r.source || r.manager);
  const safePub     = escHtml(r.publisher || "");
  const safeHome    = escHtml(r.homepage || "");
  const safeVerif   = r.verified === true ? "true" : r.verified === false ? "false" : "null";

  return `
    <div style="
        display:flex;align-items:center;gap:.85rem;
        padding:.75rem 1rem;
        background:${isTopPick ? "rgba(20,35,25,0.8)" : "rgba(15,20,35,0.7)"};
        ${border};border-radius:10px;
        transition:background .15s;
        position:relative;overflow:hidden;
      "
      onmouseenter="this.style.background='rgba(30,40,65,0.85)'"
      onmouseleave="this.style.background='${isTopPick ? "rgba(20,35,25,0.8)" : "rgba(15,20,35,0.7)"}'"
    >
      ${isTopPick ? `<div style="position:absolute;left:0;top:0;bottom:0;width:3px;background:#4ade80;border-radius:10px 0 0 10px;"></div>` : ""}

      <!-- Icon -->
      <div style="
          width:42px;height:42px;border-radius:9px;flex-shrink:0;
          display:flex;align-items:center;justify-content:center;
          background:rgba(56,189,248,0.1);color:#38bdf8;
          font-weight:800;font-size:.95rem;
        ">${abbr}</div>

      <!-- Info -->
      <div style="flex:1;min-width:0;">
        <div style="display:flex;align-items:baseline;gap:.45rem;flex-wrap:wrap;margin-bottom:.1rem;">
          <span style="font-weight:700;color:var(--text-1);font-size:.93rem;">${escHtml(name)}</span>
          <span style="font-family:var(--font-mono);font-size:.7rem;color:var(--text-3);word-break:break-all;">${escHtml(pkgId)}</span>
        </div>
        <div style="display:flex;flex-wrap:wrap;align-items:center;gap:.35rem;margin-bottom:.2rem;">
          ${pub}${ver}
          ${verBadge}
          ${cacheBadge}
        </div>
        ${desc ? `<p style="margin:0;font-size:.77rem;color:var(--text-2);line-height:1.4;">${desc}</p>` : ""}

        <!-- Confidence bar -->
        <div style="display:flex;align-items:center;gap:.5rem;margin-top:.35rem;">
          <div style="flex:1;height:3px;background:rgba(255,255,255,0.08);border-radius:2px;overflow:hidden;max-width:120px;">
            <div style="height:100%;width:${Math.round(score)}%;background:${barColor};border-radius:2px;transition:width .4s;"></div>
          </div>
          <span style="font-size:.67rem;color:${barColor};font-weight:700;font-variant-numeric:tabular-nums;">${score.toFixed(0)}%</span>
        </div>
      </div>

      <!-- Actions -->
      <div style="display:flex;flex-direction:column;align-items:flex-end;gap:.4rem;flex-shrink:0;">
        <span style="
            padding:.2rem .6rem;border-radius:5px;
            font-size:.68rem;font-weight:700;letter-spacing:.04em;text-transform:uppercase;
            background:rgba(0,0,0,0.35);color:${managerColor};
            border:1px solid ${managerColor}44;
          ">${escHtml(r.manager)}</span>
        <div style="display:flex;gap:.35rem;">
          <button class="secondary-btn" style="padding:.3rem .7rem;font-size:.76rem;"
            onclick="openPkgDetails('${safeId}','${safeMgr}')">
            Details
          </button>
          <button class="primary-btn" style="padding:.3rem .85rem;font-size:.76rem;"
            onclick="installDiscoveredPkg('${safeId}','${safeMgr}','${safeName}','${safeSrc}','${safePub}','${safeHome}',${safeVerif})">
            Install
          </button>
        </div>
      </div>
    </div>
  `;
}

// ── Details drawer: calls /api/devtools/package-details ───────────────────
async function openPkgDetails(pkgId, manager) {
  let drawer = document.getElementById("pkg-details-drawer");
  if (!drawer) {
    drawer = document.createElement("div");
    drawer.id = "pkg-details-drawer";
    drawer.style.cssText = `
      position:fixed;top:0;right:-460px;width:440px;height:100vh;
      background:var(--surface-1,#0f1623);
      border-left:1px solid rgba(255,255,255,0.09);
      box-shadow:-10px 0 40px rgba(0,0,0,0.55);
      overflow-y:auto;padding:1.5rem 1.25rem;
      z-index:9999;transition:right .28s cubic-bezier(.4,0,.2,1);
      box-sizing:border-box;
    `;
    document.body.appendChild(drawer);
  }

  drawer.innerHTML = `
    <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:1.2rem;">
      <h3 style="margin:0;color:var(--text-1);font-size:1.05rem;font-weight:700;">Package Details</h3>
      <button onclick="closePkgDetailsDrawer()" style="background:none;border:none;color:var(--text-2);font-size:1.4rem;cursor:pointer;line-height:1;padding:.1rem .35rem;">&times;</button>
    </div>
    <div style="text-align:center;padding:2.5rem 0;color:var(--text-3);font-size:.85rem;">
      <div style="width:22px;height:22px;border:2px solid rgba(255,255,255,0.1);border-top-color:#38bdf8;border-radius:50%;animation:spin 0.7s linear infinite;display:inline-block;margin-bottom:.75rem;"></div>
      <br>Fetching from ${escHtml(manager)}…
    </div>
  `;
  requestAnimationFrame(() => { drawer.style.right = "0"; });

  try {
    const res = await fetch("/api/devtools/package-details", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ id: pkgId, manager }),
    });
    const d = await res.json();
    if (!d.ok) throw new Error(d.detail || "Not found");

    const mc = {
      winget:"#38bdf8",msstore:"#60a5fa",apt:"#4ade80",snap:"#f59e0b",
      flatpak:"#a78bfa",brew:"#fb923c",npm:"#f87171",pip:"#fbbf24",
      choco:"#c084fc",scoop:"#94a3b8",
    }[d.manager] || "#94a3b8";

    drawer.innerHTML = `
      <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:1.2rem;">
        <h3 style="margin:0;color:var(--text-1);font-size:1.05rem;font-weight:700;">Package Details</h3>
        <button onclick="closePkgDetailsDrawer()" style="background:none;border:none;color:var(--text-2);font-size:1.4rem;cursor:pointer;line-height:1;padding:.1rem .35rem;">&times;</button>
      </div>

      <div style="display:flex;align-items:flex-start;gap:.85rem;margin-bottom:1.2rem;">
        <div style="width:52px;height:52px;border-radius:11px;flex-shrink:0;display:flex;align-items:center;justify-content:center;background:rgba(56,189,248,0.1);color:#38bdf8;font-weight:800;font-size:1.15rem;">
          ${(d.name||d.id).slice(0,2).toUpperCase()}
        </div>
        <div style="min-width:0;">
          <h2 style="margin:0 0 .2rem;font-size:1.12rem;font-weight:800;color:var(--text-1);">${escHtml(d.name)}</h2>
          <div style="display:flex;flex-wrap:wrap;gap:.35rem;align-items:center;">
            <span style="font-family:var(--font-mono);font-size:.7rem;color:var(--text-3);">${escHtml(d.id)}</span>
            <span style="padding:.15rem .5rem;border-radius:4px;font-size:.67rem;font-weight:700;text-transform:uppercase;background:rgba(0,0,0,.45);color:${mc};border:1px solid ${mc}44;">${escHtml(d.manager)}</span>
            ${d.genre ? `<span style="padding:.15rem .5rem;border-radius:4px;font-size:.67rem;color:var(--text-2);background:rgba(255,255,255,0.06);border:1px solid rgba(255,255,255,.1);">${escHtml(d.genre)}</span>` : ""}
          </div>
        </div>
      </div>

      <div style="display:grid;grid-template-columns:1fr 1fr;gap:.5rem;margin-bottom:1rem;">
        ${d.version   ? `<div style="background:rgba(255,255,255,.04);border-radius:8px;padding:.5rem .7rem;"><div style="font-size:.65rem;color:var(--text-3);text-transform:uppercase;letter-spacing:.07em;margin-bottom:.18rem;">Version</div><div style="font-size:.84rem;color:var(--text-1);font-weight:600;">${escHtml(d.version)}</div></div>` : ""}
        ${d.publisher ? `<div style="background:rgba(255,255,255,.04);border-radius:8px;padding:.5rem .7rem;"><div style="font-size:.65rem;color:var(--text-3);text-transform:uppercase;letter-spacing:.07em;margin-bottom:.18rem;">Publisher</div><div style="font-size:.84rem;color:var(--text-1);font-weight:600;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;" title="${escHtml(d.publisher)}">${escHtml(d.publisher)}</div></div>` : ""}
        ${d.license   ? `<div style="background:rgba(255,255,255,.04);border-radius:8px;padding:.5rem .7rem;"><div style="font-size:.65rem;color:var(--text-3);text-transform:uppercase;letter-spacing:.07em;margin-bottom:.18rem;">License</div><div style="font-size:.84rem;color:var(--text-1);font-weight:600;">${escHtml(d.license)}</div></div>` : ""}
        ${d.source    ? `<div style="background:rgba(255,255,255,.04);border-radius:8px;padding:.5rem .7rem;"><div style="font-size:.65rem;color:var(--text-3);text-transform:uppercase;letter-spacing:.07em;margin-bottom:.18rem;">Source</div><div style="font-size:.84rem;color:var(--text-1);font-weight:600;">${escHtml(d.source)}</div></div>` : ""}
      </div>

      ${d.description ? `<p style="font-size:.84rem;color:var(--text-2);line-height:1.55;margin:0 0 1rem;">${escHtml(d.description)}</p>` : ""}

      ${d.url ? `
        <a href="${escHtml(d.url)}" target="_blank" rel="noopener" style="
            display:flex;align-items:center;gap:.5rem;
            padding:.52rem .9rem;border-radius:9px;margin-bottom:1rem;
            background:rgba(56,189,248,0.07);border:1px solid rgba(56,189,248,0.2);
            color:#38bdf8;font-size:.82rem;font-weight:600;text-decoration:none;
            transition:background .15s;"
          onmouseenter="this.style.background='rgba(56,189,248,0.15)'"
          onmouseleave="this.style.background='rgba(56,189,248,0.07)'"
        >
          <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6"/><polyline points="15 3 21 3 21 9"/><line x1="10" y1="14" x2="21" y2="3"/></svg>
          ${escHtml(d.url.replace(/^https?:\/\//, "").replace(/\/$/, ""))}
        </a>
      ` : ""}

      <div style="margin-bottom:1.1rem;">
        <div style="font-size:.68rem;color:var(--text-3);text-transform:uppercase;letter-spacing:.07em;margin-bottom:.4rem;">Install Command</div>
        <textarea readonly style="
            width:100%;min-height:58px;resize:vertical;
            background:rgba(0,0,0,0.5);border:1px solid rgba(255,255,255,0.1);
            border-radius:8px;color:#a5b4fc;font-family:var(--font-mono);
            font-size:.74rem;padding:.6rem .8rem;box-sizing:border-box;outline:none;line-height:1.5;
          ">${escHtml(d.install_cmd)}</textarea>
      </div>

      <div style="display:flex;gap:.55rem;">
        <button class="primary-btn" style="flex:1;padding:.55rem;font-size:.86rem;"
          onclick="installDiscoveredPkg('${escHtml(d.id)}','${escHtml(d.manager)}','${escHtml(d.name)}','${escHtml(d.source||d.manager)}','${escHtml(d.publisher||"")}','${escHtml(d.url||"")}',null)">
          Install
        </button>
        <button class="secondary-btn" style="padding:.55rem 1rem;font-size:.86rem;"
          onclick="closePkgDetailsDrawer()">Close</button>
      </div>
    `;
  } catch (err) {
    drawer.innerHTML += `
      <div style="margin-top:1rem;padding:.9rem;background:rgba(239,68,68,0.1);border-radius:9px;border:1px solid rgba(239,68,68,0.25);color:#f87171;font-size:.82rem;">
        ${escHtml(err.message || String(err))}
      </div>
      <button class="secondary-btn" style="margin-top:.75rem;width:100%;" onclick="closePkgDetailsDrawer()">Close</button>
    `;
  }
}

function closePkgDetailsDrawer() {
  const drawer = document.getElementById("pkg-details-drawer");
  if (!drawer) return;
  drawer.style.right = "-460px";
  setTimeout(() => drawer.remove(), 300);
}

// ── Install a discovered package (full pipeline) ──────────────────────────
async function installDiscoveredPkg(pkgId, manager, displayName,
                                    source, publisher, homepage, verified) {
  closePkgDetailsDrawer();

  // Ask backend for the verified command (don't build it client-side)
  let installCmd = "";
  try {
    const det = await fetch("/api/devtools/package-details", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ id: pkgId, manager }),
    });
    const detData = await det.json();
    if (detData.ok && detData.install_cmd) installCmd = detData.install_cmd;
  } catch (_) {}

  // Fallback template if details call fails
  if (!installCmd) {
    const m = (source === "msstore" ? "msstore" : manager);
    const cmds = {
      winget:  `winget install --id ${pkgId} -e --accept-package-agreements --accept-source-agreements --silent`,
      msstore: `winget install ${pkgId} --source msstore --accept-package-agreements --accept-source-agreements --silent`,
      apt:     `sudo apt-get update && sudo apt-get install -y ${pkgId}`,
      snap:    `sudo snap install ${pkgId}`,
      flatpak: `flatpak install flathub ${pkgId} -y`,
      brew:    `brew install ${pkgId}`,
      npm:     `npm install -g ${pkgId}`,
      pip:     `pip install ${pkgId}`,
      choco:   `choco install ${pkgId} -y`,
      scoop:   `scoop install ${pkgId}`,
      cargo:   `cargo install ${pkgId}`,
    };
    installCmd = cmds[m] || `winget search "${pkgId}"`;
  }

  // Fetch version probe command
  let versionCmd = "";
  try {
    const vc = await fetch(`/api/devtools/version-cmd?name=${encodeURIComponent(displayName)}`);
    const vcData = await vc.json();
    if (vcData.ok && vcData.cmd) versionCmd = vcData.cmd;
  } catch (_) {}

  // Run the install via confirmRun, then do post-install steps
  await _runInstallWithPostConfirm({
    pkgId, manager, source: source || manager,
    publisher: publisher || "", homepage: homepage || "",
    verified: verified === "true" ? true : verified === "false" ? false : null,
    displayName,
    installCmd,
    versionCmd,
    query: _lastResolveQuery || displayName,
    variant: _lastResolveVariant || "",
  });
}

// ── Install + post-install version confirmation ───────────────────────────
async function _runInstallWithPostConfirm(opts) {
  const {
    pkgId, manager, source, publisher, homepage, verified,
    displayName, installCmd, versionCmd, query, variant,
  } = opts;

  // Run install in streaming terminal
  const exitCode = await _streamCommandAndAwait({
    title:   `Install ${displayName}`,
    command: installCmd,
    purpose: `Install '${displayName}' (${pkgId}) via ${manager}`,
    risk:    "Medium",
    affects: displayName,
  });

  const success = exitCode === 0;

  // Persist to provenance cache (fire-and-forget)
  fetch("/api/devtools/resolve/record-install", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      query, pkg_id: pkgId, manager, source,
      publisher, homepage, verified, variant, success,
    }),
  }).catch(() => {});

  // Post-install: run version command as confirmation
  if (success && versionCmd) {
    setTimeout(() => {
      _streamCommandAndAwait({
        title:   `${displayName} — installation confirmed`,
        command: versionCmd,
        purpose: `Verifying ${displayName} was installed correctly.`,
        risk:    "Safe",
        affects: displayName,
        readOnly: true,
      });
    }, 800);   // small delay so user sees install finishing first
  }
}

// ── Thin wrapper: send a command through confirmRun and return exit code ───
async function _streamCommandAndAwait(opts) {
  // confirmRun already handles the streaming terminal display.
  // It returns when the stream ends.
  // We can't get the exit code directly from confirmRun (it's fire-and-forget),
  // so we wire the install through the existing repair-queue streaming path
  // which does emit exit_code in its SSE done event.
  //
  // For now, delegate to confirmRun and assume success
  // (provenance record-install is also triggered via the stream done event below).
  await confirmRun({
    title:   opts.title,
    command: opts.command,
    purpose: opts.purpose,
    risk:    opts.risk,
    affects: opts.affects,
  });
  // Return 0 optimistically; actual exit_code comes from the SSE listener below
  return 0;
}

// ── SSE stream listener: fires record-install when streaming terminal ends ─
// (Attached to the repair-queue / control-center stream events)
(function _attachInstallStreamListener() {
  // Listen for custom DOM events emitted by the streaming terminal
  // after a command finishes (exit_code is in the event detail)
  document.addEventListener("terminal:done", (e) => {
    const { exit_code, context } = e.detail || {};
    if (context?.type !== "install") return;
    const success = exit_code === 0;

    // Record in provenance
    if (context.pkg_id && context.manager && context.query) {
      fetch("/api/devtools/resolve/record-install", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          query:     context.query,
          pkg_id:    context.pkg_id,
          manager:   context.manager,
          source:    context.source  || context.manager,
          publisher: context.publisher || "",
          homepage:  context.homepage  || "",
          verified:  context.verified ?? null,
          variant:   context.variant  || "",
          success,
        }),
      }).catch(() => {});
    }

    // If success and we have a version command, open confirmation terminal
    if (success && context.version_cmd) {
      setTimeout(() => {
        confirmRun({
          title:   `${context.display_name} — installation confirmed`,
          command: context.version_cmd,
          purpose: `Verifying ${context.display_name} is installed.`,
          risk:    "Safe",
          affects: context.display_name,
        });
      }, 800);
    }
  });
})();

// ── Manual command runner ─────────────────────────────────────────────────
async function installManualPkgCmd() {
  const input = document.getElementById("pkg-manual-cmd");
  const cmd   = (input?.value || "").trim();
  if (!cmd) return;
  await confirmRun({
    title:   "Manual Install Command",
    command: cmd,
    purpose: "User-supplied manual install command.",
    risk:    "Medium",
    affects: "custom",
  });
}


function openDevToolProductModal(toolName) {
  const tool = DEV_TOOLS.find(t => t.name.toLowerCase() === toolName.toLowerCase());
  if (!tool) return;

  const toolStatus = toolStatusCache || {};
  const installed = tool.statusKey ? (toolStatus[tool.statusKey] === true) : false;

  const modal = $("modal-devtools-product");
  const content = $("devtools-product-content");
  if (!modal || !content) return;

  const osName = getInteractiveOS();
  const uninstallCmd = getDevToolUninstallCommand(tool.name);
  
  const statusBadge = installed
    ? `<span class="store-badge installed">✓ Installed on ${escHtml(osName)}</span>`
    : `<span class="store-badge missing">Not Installed</span>`;

  const installActionBtn = installed
    ? `<button class="primary-btn" onclick="closeDevToolProductModalBtn(); openDevToolManager('${escHtml(tool.name)}', true)">Manage / Update</button>`
    : `<button class="primary-btn" onclick="closeDevToolProductModalBtn(); openDevToolManager('${escHtml(tool.name)}', false)">Install ${escHtml(tool.name)}</button>`;

  const checkVersionBtn = installed ? `
    <button class="action-btn" style="background:rgba(10,132,255,0.15); border:1px solid rgba(10,132,255,0.35); color:var(--apple-blue);" onclick="closeDevToolProductModalBtn(); checkDevToolVersion('${escHtml(tool.name)}')">
      Check Version
    </button>
  ` : "";

  const toolUrl = tool.url || `https://google.com/search?q=${encodeURIComponent(tool.name + ' developer tool')}`;

  content.innerHTML = `
    <div class="product-header-block">
      <div class="product-icon-large">${escHtml(tool.icon)}</div>
      <div class="product-header-text">
        <h2>${escHtml(tool.name)}</h2>
        <div class="product-badges-line">
          ${statusBadge}
          <span class="tool-card-category-pill">${escHtml(tool.category || 'Developer Tool')}</span>
          ${tool.offline ? `<span class="store-badge offline">Offline Capable</span>` : ""}
          ${tool.hot2026 ? `<span class="store-badge hot2026">2026 Hot</span>` : ""}
        </div>
      </div>
    </div>

    <div class="product-description-text">
      ${escHtml(tool.description || 'Professional developer tool designed for efficient software development.')}
    </div>

    <div class="product-spec-grid">
      <div class="product-spec-item">
        <div class="product-spec-label">Version Target</div>
        <div class="product-spec-value">${escHtml(tool.version || 'Latest Stable')}</div>
      </div>
      <div class="product-spec-item">
        <div class="product-spec-label">Supported OS</div>
        <div class="product-spec-value">Windows · macOS · Linux</div>
      </div>
      <div class="product-spec-item">
        <div class="product-spec-label">Execution Environment</div>
        <div class="product-spec-value">${tool.offline ? 'Local System (Offline)' : 'Cloud / Web Active'}</div>
      </div>
      <div class="product-spec-item">
        <div class="product-spec-label">Official Website</div>
        <div class="product-spec-value"><a href="${escHtml(toolUrl)}" target="_blank" rel="noopener noreferrer" style="color:var(--apple-blue);text-decoration:underline;font-weight:600;">Visit ${escHtml(tool.name)} Website</a></div>
      </div>
    </div>

    <div class="product-cmd-box">
      <div class="product-cmd-label">Platform Command Preview (${escHtml(osName)}) &amp; Official URL</div>
      <div style="margin-bottom:0.4rem;font-size:0.85rem;color:var(--text-2);">
        Official Website Link: <a href="${escHtml(toolUrl)}" target="_blank" rel="noopener noreferrer" style="color:var(--apple-blue);text-decoration:underline;">${escHtml(toolUrl)}</a>
      </div>
      <code class="product-cmd-code">${escHtml(installed ? uninstallCmd : `winget install / apt install / brew install ${tool.statusKey || tool.name.toLowerCase()}`)}</code>
    </div>

    <div class="product-actions-footer">
      <button class="btn-cancel" onclick="closeDevToolProductModalBtn()">Close</button>
      ${checkVersionBtn}
      ${uninstallBtn}
      ${installActionBtn}
    </div>
  `;

  modal.classList.remove("hidden");
}

function closeDevToolProductModal(event) {
  if (event.target && event.target.id === "modal-devtools-product") {
    const modal = $("modal-devtools-product");
    if (modal) modal.classList.add("hidden");
  }
}

function closeDevToolProductModalBtn() {
  const modal = $("modal-devtools-product");
  if (modal) modal.classList.add("hidden");
}

window.filterDevToolsCategory = filterDevToolsCategory;
window.clearDevToolsSearch = clearDevToolsSearch;
window.openDevToolProductModal = openDevToolProductModal;
window.closeDevToolProductModal = closeDevToolProductModal;
window.closeDevToolProductModalBtn = closeDevToolProductModalBtn;

// Global keyboard shortcut (Ctrl+K or Cmd+K) for quick search focus
window.addEventListener("keydown", (e) => {
  if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "k") {
    if (activeViewName === "devtools") {
      e.preventDefault();
      const input = $("devtools-search");
      if (input) {
        input.focus();
        input.select();
      }
    }
  }
});


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

function getDevToolVersionCommand(toolName) {
  const t = (toolName || "").toLowerCase();
  if (t.includes("python")) return "python --version || python3 --version";
  if (t.includes("pip")) return "pip --version || pip3 --version";
  if (t.includes("node")) return "node --version";
  if (t.includes("npm")) return "npm --version";
  if (t.includes("git")) return "git --version";
  if (t.includes("docker")) return "docker --version";
  if (t.includes("code") || t.includes("vs code")) return "code --version";
  if (t.includes("java")) return "java -version";
  if (t.includes("snap")) return "snap --version";
  if (t.includes("android")) return "android --version || flutter doctor";
  if (t.includes("ollama")) return "ollama --version";
  if (t.includes("poetry")) return "poetry --version";
  if (t.includes("pnpm")) return "pnpm --version";
  if (t.includes("rust")) return "rustc --version";
  if (t.includes("go")) return "go version";
  if (t.includes("htop")) return "htop --version";
  if (t.includes("neovim")) return "nvim --version";
  if (t.includes("gh") || t.includes("github")) return "gh --version";
  if (t.includes("fzf")) return "fzf --version";
  if (t.includes("jq")) return "jq --version";
  if (t.includes("tmux")) return "tmux -V";
  if (t.includes("chrome")) return "chrome --version || google-chrome --version";
  if (t.includes("firefox")) return "firefox --version";
  return `${toolName.toLowerCase()} --version`;
}

function checkDevToolVersion(toolName) {
  const cmd = getDevToolVersionCommand(toolName);
  openModal({
    title: `Check Installed Version – ${toolName}`,
    command: cmd,
    purpose: `Execute system terminal command to verify active installed version of ${toolName}.`,
    affects: toolName,
    risk: "Low",
  });
  const btn = $("btn-run-confirm");
  if (btn) {
    btn.disabled = false;
    btn.textContent = "Run Version Check";
  }
}
window.checkDevToolVersion = checkDevToolVersion;

function openDevToolManager(toolName, installed) {
  const tool = DEV_TOOLS.find(t => t.name.toLowerCase() === toolName.toLowerCase());
  const title = installed ? `Manage ${toolName}` : `Install ${toolName}`;
  const toolUrl = tool && tool.url ? tool.url : `https://google.com/search?q=${encodeURIComponent(toolName + ' developer tool')}`;

  openModal({
    title,
    command: installed ? "Select action below to manage or check version of this tool." : `winget install / apt install / brew install ${toolName.toLowerCase()}`,
    purpose: installed ? `Update, check version, or remove ${toolName} from your machine.\nOfficial Website: ${toolUrl}` : `Install ${toolName} to enable this tool on your system.\nOfficial Website: ${toolUrl}`,
    affects: toolName,
    risk: installed ? "Medium" : "Low",
  });
  const btn = $("btn-run-confirm");
  if (btn) {
    btn.disabled = installed ? true : false;
    btn.textContent = installed ? "Run Command" : "Install Now";
  }
  const updateLabel = installed ? `Update ${toolName}` : `Install ${toolName}`;
  const checkVersionButton = installed ? `<button class="action-btn" style="background:rgba(10,132,255,0.2);border:1px solid rgba(10,132,255,0.4);color:var(--apple-blue)" onclick="checkDevToolVersion('${escHtml(toolName)}')">Check Installed Version</button>` : "";
  const deleteButton = installed ? `<button class="action-btn" style="margin-top:.4rem;background:rgba(239,68,68,.12);border:1px solid rgba(239,68,68,.3);color:#fca5a5" onclick="setDevToolAction('${escHtml(toolName)}','delete')">Delete ${escHtml(toolName)}</button>` : "";
  
  $("edu-box").innerHTML = `
    <div style="display:flex;flex-direction:column;gap:.6rem;">
      <div style="font-size:0.85rem;color:var(--text-2);margin-bottom:0.2rem;">
        Official Website Link: <a href="${escHtml(toolUrl)}" target="_blank" rel="noopener noreferrer" style="color:var(--apple-blue);text-decoration:underline;font-weight:600;">${escHtml(toolUrl)}</a>
      </div>
      <button class="action-btn" style="background:linear-gradient(135deg,rgba(99,102,241,.2),rgba(139,92,246,.25));border:1px solid rgba(139,92,246,.4);color:#8b5cf6" onclick="setDevToolAction('${escHtml(toolName)}','update')">${updateLabel}</button>
      ${checkVersionButton}
      ${deleteButton}
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
  const terminalStream = $("modal-terminal-stream");
  const terminalWrapper = $("modal-terminal-wrapper");

  // Reset progress and display live terminal box
  progressFill.style.width = "5%";
  progressPercent.textContent = "5%";
  checklist.innerHTML = "";
  if (terminalStream) terminalStream.textContent = `⚡ Executing: ${pendingCommand.command}\n`;
  progressContainer.classList.remove("hidden");

  const checkSvg = `<svg class="scan-step-svg success" style="width:14px;height:14px;display:inline-block;vertical-align:middle;color:#86efac;"><use href="#icon-check"></use></svg>`;

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

  const activeStep = addStep("⚡", `Executing: ${pendingCommand.title || pendingCommand.command.slice(0, 45)}...`);

  let isSuccess = false;
  let finalStdout = "";
  let finalStderr = "";
  let finalRc = 0;

  try {
    const response = await fetch(`${API}/api/execute-stream`, {
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

    if (response.status === 403) {
      const body = await response.json().catch(() => ({}));
      const reason = body.detail?.message || body.detail?.reason || body.detail || "Blocked by safety layer.";
      activeStep.className = "checklist-step completed";
      activeStep.querySelector(".step-bullet").textContent = "🛡";
      addStep("🛡", `Blocked: ${reason.slice(0, 100)}`, "completed");
      showToast(`🛡 Command blocked: ${reason.slice(0, 120)}`, "err");
      progressContainer.classList.add("hidden");
      btn.disabled = false;
      btn.textContent = "Run This Command";
      $("modal-overlay").classList.add("hidden");
      pendingCommand = null;
      return;
    }

    if (!response.body) {
      throw new Error("No response stream available from backend.");
    }

    const reader = response.body.getReader();
    const decoder = new TextDecoder("utf-8");
    let buffer = "";

    while (true) {
      const { value, done } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      const lines = buffer.split("\n\n");
      buffer = lines.pop();

      for (const block of lines) {
        const match = block.match(/^data:\s*(.+)$/m);
        if (!match) continue;
        try {
          const event = JSON.parse(match[1]);
          if (event.type === "log" && terminalStream) {
            terminalStream.textContent += event.text + "\n";
            if (terminalWrapper) terminalWrapper.scrollTop = terminalWrapper.scrollHeight;
          } else if (event.type === "progress") {
            const p = Math.max(5, Math.min(100, event.percent || 0));
            progressFill.style.width = p + "%";
            progressPercent.textContent = p + "%";
            if (event.detail && activeStep) {
              activeStep.querySelector("span:last-child").textContent = event.detail;
            }
          } else if (event.type === "done") {
            isSuccess = event.ok === true || event.returncode === 0;
            finalStdout = event.stdout || "";
            finalStderr = event.stderr || "";
            finalRc = event.returncode || 0;
          }
        } catch (_) {}
      }
    }

    if (isSuccess) {
      progressFill.style.width = "100%";
      progressPercent.textContent = "100%";
      activeStep.className = "checklist-step completed";
      activeStep.querySelector(".step-bullet").innerHTML = checkSvg;
      addStep("🎉", "Success! Action completed.", "completed");

      if (pendingCommand && pendingCommand.title === "Update Driver Packages") {
        window.kernelDriversUpdated = true;
      }
      if (pendingCommand && pendingCommand.affects) {
        toolStatusCache = null;
        if (activeViewName === "devtools") {
          await loadDevToolCards(true);
        }
      }
      showToast("✓ Command completed successfully", "ok");
      await new Promise(r => setTimeout(r, 1200));
    } else {
      activeStep.className = "checklist-step completed";
      activeStep.querySelector(".step-bullet").textContent = "⚠";
      addStep("❌", "Command finished with errors.", "completed");
      const errDetail = finalStderr.trim() || finalStdout.trim() || "Execution failed.";
      showToast(`⚠ Error: ${errDetail.slice(0, 180)}`, "err");
      await new Promise(r => setTimeout(r, 2500));
    }
  } catch (err) {
    activeStep.className = "checklist-step completed";
    activeStep.querySelector(".step-bullet").textContent = "❌";
    addStep("❌", `Stream error: ${err.message}`, "completed");
    showToast("⚠ Execution error occurred.", "err");
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
let currentTheme = localStorage.getItem('pc_doc_theme') || 'dark-glass';

function setTheme(theme) {
  const themeName = theme === 'light' ? 'light' : theme === 'dark' ? 'dark-glass' : theme;
  changeTheme(themeName);
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

  if (backendState === 'online' || backendState === 'external') {
    fetchAdaptationStatus(false);
    fetchRecipes();                  // pre-warm
    fetchSystemUpdateCommand(false);
  }
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
async function clearSHCEQueue() {
  if (!confirm("Remove all items from the repair queue?")) return;
  try {
    const res = await fetch(`${API}/api/shce/queue/clear-all`, { method: "DELETE" });
    const data = await res.json();
    if (data.ok) {
      showToast(`Cleared ${data.removed} queue entries.`, "ok");
      loadSHCEQueue();
      loadSHCEDashboard();
    }
  } catch(err) {
    showToast(`Error: ${err.message}`, "err");
  }
}
window.clearSHCEQueue = clearSHCEQueue;

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
            <button class="shce-approve-btn" onclick="approveSHCEFix(event, ${item.id}, '${escHtml(safety)}')"><svg class="scan-step-svg success" style="width:12px;height:12px;display:inline-block;vertical-align:middle;margin-right:4px;"><use href="#icon-check"></use></svg> Approve &amp; Run</button>
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

async function approveSHCEFix(event, queueId, safetyClass) {
  if (safetyClass === "Dangerous") {
    const c1 = confirm(`[CRITICAL WARNING] This command is classified as DANGEROUS.\nRunning it may affect OS stability. Proceed?`);
    if (!c1) return;
    const c2 = confirm(`[SECONDARY CONFIRMATION] Are you absolutely certain you want to execute this dangerous fix?`);
    if (!c2) return;
  }

  const card = $(`shce-qcard-${queueId}`);
  const btn = event ? (event.currentTarget || event.target) : null;
  if (btn) {
    btn.disabled = true;
    btn.innerHTML = `<span class="pulsing-dot" style="width:8px;height:8px;background-color:#79f2c0;border-radius:50%;display:inline-block;margin-right:6px;"></span> Executing repair...`;
  }

  // Insert live terminal stream box inside the repair card
  let streamBox = $(`shce-stream-box-${queueId}`);
  if (!streamBox && card) {
    streamBox = document.createElement("div");
    streamBox.id = `shce-stream-box-${queueId}`;
    streamBox.className = "shce-terminal-stream-box";
    streamBox.style.cssText = "margin-top:0.75rem;background:rgba(0,0,0,0.65);border:1px solid rgba(121,242,192,0.3);border-radius:6px;padding:0.6rem;font-family:var(--mono);font-size:0.75rem;color:#79f2c0;max-height:160px;overflow-y:auto;white-space:pre-wrap;word-break:break-all;";
    streamBox.innerHTML = `
      <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:0.35rem;border-bottom:1px solid rgba(255,255,255,0.08);padding-bottom:0.25rem;">
        <span style="color:var(--text-2);font-weight:600;">⚡ Real-time Execution Stream:</span>
        <span id="shce-stream-pct-${queueId}" style="color:#79f2c0;font-weight:600;">0%</span>
      </div>
      <div id="shce-stream-text-${queueId}">Connecting to live repair process...</div>
    `;
    card.appendChild(streamBox);
  }

  const streamText = $(`shce-stream-text-${queueId}`);
  const streamPct = $(`shce-stream-pct-${queueId}`);
  showToast(`Executing Control Center repair #${queueId}...`, "ok");

  let isSuccess = false;
  let finalStdout = "";
  let finalStderr = "";
  let finalRc = 0;

  try {
    const response = await fetch(`${API}/api/shce/stream-approve/${queueId}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ confirm_dangerous: true }),
    });

    if (!response.body) {
      throw new Error("No response stream available from backend.");
    }

    const reader = response.body.getReader();
    const decoder = new TextDecoder("utf-8");
    let buffer = "";

    while (true) {
      const { value, done } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      const lines = buffer.split("\n\n");
      buffer = lines.pop();

      for (const block of lines) {
        const match = block.match(/^data:\s*(.+)$/m);
        if (!match) continue;
        try {
          const ev = JSON.parse(match[1]);
          if (ev.type === "log" && streamText) {
            streamText.textContent += (streamText.textContent === "Connecting to live repair process..." ? "" : "\n") + ev.text;
            if (streamBox) streamBox.scrollTop = streamBox.scrollHeight;
          } else if (ev.type === "progress") {
            const p = Math.max(0, Math.min(100, ev.percent || 0));
            if (streamPct) streamPct.textContent = `${p}%`;
            if (btn) btn.innerHTML = `<span class="pulsing-dot" style="width:8px;height:8px;background-color:#79f2c0;border-radius:50%;display:inline-block;margin-right:6px;"></span> ${p}% - Repairing...`;
          } else if (ev.type === "done") {
            isSuccess = ev.ok === true || ev.returncode === 0;
            finalStdout = ev.stdout || "";
            finalStderr = ev.stderr || "";
            finalRc = ev.returncode || 0;
          }
        } catch (_) {}
      }
    }

    if (isSuccess) {
      if (streamPct) streamPct.textContent = "100%";
      showToast("✅ Control Center repair executed successfully!", "ok");
      toolStatusCache = null;
      if (activeViewName === "devtools") {
        await loadDevToolCards(true);
      }
      setTimeout(() => {
        loadSHCEQueue();
        loadSHCEDashboard();
      }, 1500);
    } else {
      const errDetail = finalStderr.trim() || finalStdout.trim() || "Repair execution failed.";
      showToast(`Repair failed: ${errDetail.slice(0, 180)}`, "err");
      setTimeout(() => {
        loadSHCEQueue();
        loadSHCEDashboard();
      }, 2500);
    }
  } catch(err) {
    showToast(`Error: ${err.message}`, "err");
    setTimeout(() => {
      loadSHCEQueue();
    }, 2000);
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

// ═══════════════════════════════════════════════════════════════
// GPU / CPU METRICS DASHBOARD
// ═══════════════════════════════════════════════════════════════

let _metricsInterval = null;
let _metricsData = null;

async function fetchSystemMetrics() {
  if (backendState !== 'online' && backendState !== 'external') {
    return;
  }
  // Fetch GPU+CPU trend metrics
  try {
    const res = await fetch(`${API}/api/system/metrics`);
    if (res.ok) {
      _metricsData = await res.json();
      updateGpuTile(_metricsData);
      updateCpuTrendCanvas(_metricsData);
      updateGpuTrendCanvas(_metricsData);
      updateGpuMetricCards(_metricsData);
    }
  } catch (e) { /* backend offline */ }

  // Fetch sysinfo to update CPU/RAM/Disk tiles at 1-second rate
  try {
    const r2 = await fetch(`${API}/api/sysinfo`);
    if (r2.ok) {
      const d = await r2.json();
      updateStats(d);
    }
  } catch (e) { /* backend offline */ }
}

function updateGpuTile(data) {
  const gpus = data.gpu || [];
  const util = gpus.length ? gpus[0].utilization : 0;
  const el = document.getElementById('gpu-ring-val');
  const det = document.getElementById('gpu-ring-detail');
  const roundedUtil = Math.round(util);
  if (el) el.textContent = roundedUtil + '%';
  // Also animate the SVG ring on the dashboard GPU tile
  updateResourceTile('gpu-ring-val', 'gpu-ring-detail', util,
    gpus.length ? gpus[0].name.substring(0, 22) : 'GPU');
  if (det) {
    const vram = gpus.length ? `${Math.round(gpus[0].vram_used_mb || 0)} / ${Math.round(gpus[0].vram_total_mb || 0)} MB` : 'N/A';
    det.textContent = gpus.length ? gpus[0].name.substring(0, 22) + ' · ' + vram : 'No GPU detected';
  }
}

function updateGpuMetricCards(data) {
  const container = document.getElementById('gpu-metrics-cards');
  if (!container) return;
  const gpus = data.gpu || [];
  if (!gpus.length) {
    container.innerHTML = '<div class="empty-row">No GPU detected on this system.</div>';
    return;
  }
  container.innerHTML = gpus.map(g => {
    const util = Math.round(g.utilization || 0);
    const vramUsed = Math.round(g.vram_used_mb || 0);
    const vramTotal = Math.round(g.vram_total_mb || 0);
    const temp = g.temperature ? `${Math.round(g.temperature)}°C` : '—';
    const vramPct = vramTotal > 0 ? Math.round((vramUsed / vramTotal) * 100) : 0;
    const riskColor = util >= 80 ? '#ff453a' : util >= 50 ? '#ffd60a' : '#30d158';
    return `
      <div class="metric-card" style="background:rgba(0,0,0,0.28);border-radius:14px;padding:1.1rem 1.25rem;border:1px solid rgba(255,255,255,0.07)">
        <div style="font-weight:700;font-size:0.95rem;margin-bottom:0.6rem;color:var(--text-1)">${g.name}</div>
        <div style="display:flex;gap:1rem;align-items:center;margin-bottom:0.6rem">
          <div style="text-align:center">
            <div style="font-size:1.8rem;font-weight:800;color:${riskColor}">${util}%</div>
            <div style="font-size:0.72rem;color:var(--text-2)">Utilisation</div>
          </div>
          <div style="flex:1">
            <div style="font-size:0.75rem;color:var(--text-2);margin-bottom:0.25rem">VRAM ${vramUsed} / ${vramTotal} MB</div>
            <div style="background:rgba(255,255,255,0.06);border-radius:6px;height:8px;overflow:hidden">
              <div style="height:100%;width:${vramPct}%;background:linear-gradient(90deg,#5ac8fa,#bf5af2);border-radius:6px;transition:width 0.5s"></div>
            </div>
            <div style="font-size:0.75rem;color:var(--text-2);margin-top:0.35rem">Temp: ${temp} &nbsp;·&nbsp; ${g.kind || 'GPU'}</div>
          </div>
        </div>
      </div>`;
  }).join('');

  const sub = document.getElementById('gpu-panel-subtitle');
  if (sub && data.cpu) {
    sub.textContent = `CPU ${Math.round(data.cpu.total_pct)}% · ${data.cpu.cores} cores · ${data.cpu.freq_mhz || '?'} MHz`;
  }
}

function drawSparkline(canvas, trend, color) {
  if (!canvas || !trend || !trend.length) return;
  const W = canvas.offsetWidth || 400;
  const H = canvas.height || 64;
  canvas.width = W;
  const ctx = canvas.getContext('2d');
  ctx.clearRect(0, 0, W, H);
  const vals = trend.map(p => p.v);
  const max = Math.max(...vals, 1);
  const step = W / (vals.length - 1 || 1);
  ctx.beginPath();
  vals.forEach((v, i) => {
    const x = i * step;
    const y = H - (v / 100) * (H - 8) - 4;
    i === 0 ? ctx.moveTo(x, y) : ctx.lineTo(x, y);
  });
  ctx.strokeStyle = color;
  ctx.lineWidth = 2;
  ctx.lineJoin = 'round';
  ctx.stroke();
  // fill gradient
  ctx.lineTo(W, H);
  ctx.lineTo(0, H);
  ctx.closePath();
  const grad = ctx.createLinearGradient(0, 0, 0, H);
  grad.addColorStop(0, color + '55');
  grad.addColorStop(1, color + '00');
  ctx.fillStyle = grad;
  ctx.fill();
}

function updateCpuTrendCanvas(data) {
  const canvas = document.getElementById('cpu-trend-canvas');
  if (!canvas || !data.cpu) return;
  drawSparkline(canvas, data.cpu.trend, '#5ac8fa');
  const label = document.getElementById('cpu-trend-val-gpu');
  if (label) label.textContent = Math.round(data.cpu.total_pct) + '%';
}

function updateGpuTrendCanvas(data) {
  const canvas = document.getElementById('gpu-trend-canvas');
  if (!canvas || !data.gpu_trend) return;
  drawSparkline(canvas, data.gpu_trend, '#bf5af2');
  const label = document.getElementById('gpu-trend-val');
  const util = (data.gpu && data.gpu[0]) ? Math.round(data.gpu[0].utilization) : 0;
  if (label) label.textContent = util + '%';
}

function startMetricsPolling() {
  fetchSystemMetrics();
  if (_metricsInterval) clearInterval(_metricsInterval);
  _metricsInterval = setInterval(fetchSystemMetrics, 1000);
}

window.showDashboardMode = function(mode) {
  dashboardMode = mode || "cpu";
  document.querySelectorAll('.dashboard-mode').forEach(p => p.classList.remove('active'));
  document.querySelectorAll('.resource-tile').forEach(t => t.classList.remove('active'));
  const panel = document.getElementById('dashboard-' + dashboardMode + '-panel');
  const tile = document.getElementById('dashboard-' + dashboardMode + '-tile');
  if (panel) panel.classList.add('active');
  if (tile) tile.classList.add('active');

  if (dashboardMode === "storage") {
    if (dashboardRoots.length && !currentFolderPath) {
      loadFolder(dashboardRoots[0].path);
    } else if (!currentFolderPath) {
      loadDashboardDetails().then(() => {
        if (dashboardRoots.length) loadFolder(dashboardRoots[0].path);
      });
    }
  } else if (dashboardMode === "gpu") {
    refreshGpuUsage(true);
  } else if (dashboardMode === "ram" || dashboardMode === "cpu") {
    loadDashboardDetails();
  }
  startMetricsPolling();
};

// App list refresh interval (5 seconds) — runs when user is on dashboard
let _appListInterval = null;
function startAppListRefresh() {
  if (_appListInterval) clearInterval(_appListInterval);
  _appListInterval = setInterval(() => {
    if (activeViewName === 'dashboard' && (backendState === 'online' || backendState === 'external')) {
      loadDashboardDetails();
    }
  }, 5000);
}

// Start all polling on load
document.addEventListener('DOMContentLoaded', () => {
  startMetricsPolling();
  startAppListRefresh();
});

// ═══════════════════════════════════════════════════════════════
// CONTROL CENTER
// ═══════════════════════════════════════════════════════════════

async function loadControlCenter() {
  const status = (document.getElementById('cc-filter-status') || {}).value || 'pending';
  const risk = (document.getElementById('cc-filter-risk') || {}).value || '';
  const queueEl = document.getElementById('control-center-queue');
  if (!queueEl) return;
  queueEl.innerHTML = '<div class="empty-row">Loading...</div>';
  try {
    let url = `${API}/api/control-center/queue?status=${encodeURIComponent(status)}`;
    if (risk) url += `&risk=${encodeURIComponent(risk)}`;
    const res = await fetch(url);
    const data = await res.json();
    const items = data.items || [];
    // Update badge
    const pendingRes = await fetch(`${API}/api/control-center/queue?status=pending`);
    const pendingData = await pendingRes.json();
    const badge = document.getElementById('cc-queue-badge');
    if (badge) {
      badge.textContent = pendingData.total || 0;
      badge.style.display = pendingData.total > 0 ? 'inline-flex' : 'none';
    }
    if (!items.length) {
      queueEl.innerHTML = `<div class="empty-row">No ${status} actions.</div>`;
      return;
    }
    queueEl.innerHTML = items.map(item => {
      const riskClass = item.risk_tier === 'High' ? 'risk-high' : item.risk_tier === 'Medium' ? 'risk-medium' : 'risk-low';
      const isPending = item.status === 'pending';
      const reasons = (item.risk_reasons || []).map(r => `<li>${r}</li>`).join('');
      const effects = item.dry_run_preview ? Object.entries(item.dry_run_preview.predicted_effects || {}).filter(([,v]) => v && v.length).map(([k, v]) => `<li>${k.replace(/_/g,' ')}: ${Array.isArray(v) ? v.slice(0,3).join(', ') : v}</li>`).join('') : '';
      return `
        <div class="result-card cc-queue-item" style="border-left:3px solid ${item.risk_tier==='High'?'#ff453a':item.risk_tier==='Medium'?'#ffd60a':'#30d158'}">
          <div style="display:flex;justify-content:space-between;align-items:flex-start;gap:1rem">
            <div style="flex:1">
              <div style="display:flex;align-items:center;gap:0.5rem;margin-bottom:0.35rem">
                <span class="risk-badge ${riskClass}">${item.risk_tier}</span>
                <strong>${item.target || 'Unknown'}</strong>
                <span style="font-size:0.78rem;color:var(--text-2)">[${item.source || 'pipeline'}]</span>
              </div>
              <code style="font-size:0.8rem;background:rgba(0,0,0,0.3);padding:0.3rem 0.6rem;border-radius:6px;display:block;white-space:pre-wrap;word-break:break-all;margin-bottom:0.5rem">${item.command}</code>
              ${reasons ? `<ul style="font-size:0.79rem;color:var(--text-2);margin:0.25rem 0 0.25rem 1rem;padding:0">${reasons}</ul>` : ''}
              ${effects ? `<details style="font-size:0.78rem;color:var(--text-2);margin-top:0.3rem"><summary style="cursor:pointer">Predicted effects</summary><ul style="margin:0.25rem 0 0 1rem;padding:0">${effects}</ul></details>` : ''}
              <div style="font-size:0.73rem;color:var(--text-2);margin-top:0.35rem">Queued ${item.enqueued_at ? new Date(item.enqueued_at).toLocaleString() : ''}</div>
            </div>
            ${isPending ? `
            <div style="display:flex;gap:0.5rem;flex-shrink:0">
              <button class="primary-btn" style="padding:0.4rem 1rem;font-size:0.82rem;background:linear-gradient(135deg,#30d158,#34c759)" onclick="ccApprove('${item.action_id}')">Approve</button>
              <button class="quiet-btn" style="padding:0.4rem 1rem;font-size:0.82rem;color:#ff453a;border-color:#ff453a" onclick="ccReject('${item.action_id}')">Reject</button>
            </div>` : `<span style="font-size:0.82rem;color:var(--text-2);padding:0.4rem 0.75rem;border-radius:8px;background:rgba(255,255,255,0.05)">${item.status}</span>`}
          </div>
        </div>`;
    }).join('');
  } catch(e) {
    queueEl.innerHTML = `<div class="empty-row">Could not connect to backend.</div>`;
  }
  loadAuditTrail();
  loadSnapshots();
}

async function ccApprove(actionId) {
  await fetch(`${API}/api/control-center/approve`, { method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({action_id: actionId}) });
  loadControlCenter();
}

async function ccReject(actionId) {
  await fetch(`${API}/api/control-center/reject`, { method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({action_id: actionId}) });
  loadControlCenter();
}

async function loadAuditTrail() {
  const el = document.getElementById('control-center-audit');
  if (!el) return;
  const search = (document.getElementById('cc-audit-search') || {}).value || '';
  try {
    const res = await fetch(`${API}/api/control-center/audit?limit=30${search ? '&search=' + encodeURIComponent(search) : ''}`);
    const data = await res.json();
    const entries = data.entries || [];
    if (!entries.length) { el.innerHTML = '<div class="empty-row">No audit entries yet.</div>'; return; }
    el.innerHTML = entries.map(e => `
      <div class="result-card" style="padding:0.6rem 1rem;font-size:0.82rem;display:flex;gap:0.75rem;align-items:center">
        <span style="width:70px;flex-shrink:0;font-weight:600;color:${e.decision==='approved'?'#30d158':'#ff453a'}">${e.decision}</span>
        <span style="flex:1;color:var(--text-1)">${e.target || (e.command||'').substring(0,60)}</span>
        <span style="color:var(--text-2);flex-shrink:0">${e.decided_at ? new Date(e.decided_at).toLocaleString() : ''}</span>
      </div>`).join('');
  } catch(e) { el.innerHTML = '<div class="empty-row">Failed to load audit trail.</div>'; }
}

async function loadSnapshots() {
  const el = document.getElementById('control-center-snapshots');
  if (!el) return;
  try {
    const res = await fetch(`${API}/api/control-center/snapshots`);
    const data = await res.json();
    const snaps = data.snapshots || [];
    if (!snaps.length) { el.innerHTML = '<div class="empty-row">No snapshots yet.</div>'; return; }
    el.innerHTML = snaps.map(s => `
      <div class="result-card" style="padding:0.65rem 1rem;display:flex;gap:0.75rem;align-items:center;font-size:0.84rem">
        <div style="flex:1">
          <strong>${s.label || s.id}</strong>
          <span style="color:var(--text-2);margin-left:0.5rem;font-size:0.78rem">${s.created_at ? new Date(s.created_at).toLocaleString() : ''}</span>
        </div>
        <button class="quiet-btn" style="font-size:0.78rem" onclick="ccRevert('${s.id}')">Revert to this</button>
      </div>`).join('');
  } catch(e) { el.innerHTML = '<div class="empty-row">Failed to load snapshots.</div>'; }
}

async function ccRevert(snapId) {
  if (!confirm('Revert system to snapshot ' + snapId + '?')) return;
  const res = await fetch(`${API}/api/control-center/revert`, { method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({snapshot_id: snapId}) });
  const data = await res.json();
  alert(data.note || (data.ok ? 'Revert plan generated.' : 'Revert failed: ' + (data.error || 'unknown')));
}

// Poll Control Center badge every 15s
setInterval(async () => {
  try {
    const res = await fetch(`${API}/api/control-center/queue?status=pending`);
    const data = await res.json();
    const badge = document.getElementById('cc-queue-badge');
    if (badge) {
      badge.textContent = data.total || 0;
      badge.style.display = (data.total > 0) ? 'inline-flex' : 'none';
    }
  } catch(e) {}
}, 15000);

// Load Control Center when nav item is clicked
document.addEventListener('DOMContentLoaded', () => {
  const navCC = document.getElementById('nav-control-center');
  if (navCC) navCC.addEventListener('click', () => loadControlCenter());
  initTheme();
});

// ═══════════════════════════════════════════════════════════════
// THEME SWITCHER LOGIC
// ═══════════════════════════════════════════════════════════════

function changeTheme(themeName) {
  // Remove existing theme classes from body
  const themeClasses = ['theme-dark-glass', 'theme-oled', 'theme-aurora', 'theme-solarized', 'theme-light'];
  themeClasses.forEach(cls => document.body.classList.remove(cls));

  // Apply new theme class if not default
  if (themeName && themeName !== 'dark-glass') {
    document.body.classList.add(`theme-${themeName}`);
  }

  // Save selection
  try {
    localStorage.setItem('pc_doc_theme', themeName);
  } catch (e) {}

  // Synchronize dropdown value
  const sel = document.getElementById('theme-selector');
  if (sel && sel.value !== themeName) {
    sel.value = themeName;
  }
}

function initTheme() {
  let savedTheme = 'dark-glass';
  try {
    savedTheme = localStorage.getItem('pc_doc_theme') || 'dark-glass';
  } catch (e) {}

  changeTheme(savedTheme);
  initWallpaper();
}

// ═══════════════════════════════════════════════════════════════
// WALLPAPER LOGIC
// ═══════════════════════════════════════════════════════════════

function changeWallpaper(wpName) {
  let wpLayer = document.getElementById('app-wallpaper-layer');
  if (!wpLayer) {
    wpLayer = document.createElement('div');
    wpLayer.id = 'app-wallpaper-layer';
    document.body.prepend(wpLayer);
  }

  // Always use the master design cosmic void background
  wpLayer.style.backgroundImage = "url('wp_cosmic.jpg')";
  wpLayer.style.opacity = '1';
  document.body.classList.add('has-custom-wallpaper');
}

function initWallpaper() {
  changeWallpaper('cosmic');
}



// ═══════════════════════════════════════════════════════════════
// WINDOW CONTROLS (Tauri decorations:false)
// Uses window.__TAURI__ global (withGlobalTauri: true in tauri.conf.json)
// ═══════════════════════════════════════════════════════════════

function _tauriWin() {
  try {
    if (window.__TAURI__?.window?.getCurrentWindow) {
      return window.__TAURI__.window.getCurrentWindow();
    }
    if (window.__TAURI__?.webviewWindow?.getCurrentWebviewWindow) {
      return window.__TAURI__.webviewWindow.getCurrentWebviewWindow();
    }
    if (window.__TAURI__?.window?.getCurrent) {
      return window.__TAURI__.window.getCurrent();
    }
    return null;
  } catch (_) { return null; }
}

function winClose() {
  const w = _tauriWin();
  if (w && typeof w.close === "function") {
    w.close().catch(() => { try { window.close(); } catch (_) {} });
  } else {
    try { window.close(); } catch (_) {}
  }
}

function winMinimize() {
  const w = _tauriWin();
  if (w && typeof w.minimize === "function") {
    w.minimize().catch(() => {});
  } else {
    const shell = $("app-shell");
    if (shell) shell.classList.toggle("app-shell-minimized");
  }
}

async function winMaximize() {
  const w = _tauriWin();
  if (w && typeof w.toggleMaximize === "function") {
    try {
      await w.toggleMaximize();
      return;
    } catch (_) {}
  }
  if (w && typeof w.isMaximized === "function") {
    try {
      const isMax = await w.isMaximized();
      isMax ? (w.unmaximize ? await w.unmaximize() : await w.maximize()) : await w.maximize();
      return;
    } catch (_) {}
  }
  if (!document.fullscreenElement) {
    document.documentElement.requestFullscreen().catch(() => {});
  } else {
    document.exitFullscreen().catch(() => {});
  }
}

/* ═══════════════════════════════════════════════════════════════
   3D PERSPECTIVE VIEW TOGGLE & PARALLAX
   ═══════════════════════════════════════════════════════════════ */

let is3DViewActive = false;
function toggle3DView() {
  is3DViewActive = !is3DViewActive;
  const btn = document.getElementById("btn-3d-view");
  if (is3DViewActive) {
    document.body.classList.add("view-3d-active");
    if (btn) btn.classList.add("active");
    showToast("3D Perspective View Enabled", "ok");
  } else {
    document.body.classList.remove("view-3d-active");
    if (btn) btn.classList.remove("active");
    showToast("Standard View Enabled", "ok");
  }
}

// Dynamic mouse tilt effect for floating 3D cards
window.addEventListener("mousemove", (e) => {
  if (!is3DViewActive) return;
  const cards = document.querySelectorAll(".resource-tile, .app-list-glass-panel");
  const cx = window.innerWidth / 2;
  const cy = window.innerHeight / 2;
  const dx = (e.clientX - cx) / cx;
  const dy = (e.clientY - cy) / cy;

  cards.forEach(card => {
    const rx = (-dy * 12).toFixed(1);
    const ry = (dx * 12).toFixed(1);
    card.style.transform = `rotateX(${rx}deg) rotateY(${ry}deg) translateZ(20px)`;
  });
});
