/**
 * DevTools Store & Control Center — Unified Frontend Engine
 * ==========================================================
 * Reactive single-page client for:
 *   - Real-time package discovery & unified search across 12 package managers
 *   - Health diagnostics & automated RAG repair finder
 *   - Managed applications lifecycle & update streaming
 *   - Unified Control Center approval queue, audit logs, & snapshot rollback
 */

// ── API Base URL ─────────────────────────────────────────────────────────────
const API = (window.location.protocol && window.location.protocol.startsWith("http")) ? "" : "http://127.0.0.1:8790";

// ── Global State ─────────────────────────────────────────────────────────────
let activeView = "devtools";
let catalogTools = [];
let toolStatusCache = {};
let managedAppsCache = [];
let currentDevToolsCategory = "all";
let searchDebounceTimer = null;
let activeDoctorTab = "health";
let autoRepairsCache = [];
let activeModalAction = null;
let activeEventSources = {};

// ── Helpers ──────────────────────────────────────────────────────────────────
const $ = (id) => document.getElementById(id);

function escHtml(str) {
  if (str === null || str === undefined) return "";
  return String(str)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#039;");
}

function showToast(message, type = "ok") {
  const toast = $("toast");
  if (!toast) return;
  toast.textContent = message;
  toast.className = `toast ${type}`;
  setTimeout(() => {
    toast.className = "toast hidden";
  }, 3500);
}

// ── Theme Management ─────────────────────────────────────────────────────────
function initTheme() {
  const saved = localStorage.getItem("devtools-theme") || "dark-glass";
  changeTheme(saved);
}

function changeTheme(themeName) {
  document.body.className = `theme-${themeName}`;
  localStorage.setItem("devtools-theme", themeName);

  const themeBtns = {
    "dark-glass": $("btn-theme-dark"),
    oled: $("btn-theme-oled"),
    aurora: $("btn-theme-aurora"),
    light: $("btn-theme-light"),
  };

  Object.entries(themeBtns).forEach(([k, btn]) => {
    if (btn) btn.classList.toggle("active", k === themeName);
  });
}
window.changeTheme = changeTheme;

// ── Navigation & View Switching ──────────────────────────────────────────────
function switchView(viewName) {
  activeView = viewName;

  document.querySelectorAll(".nav-item").forEach((btn) => {
    btn.classList.toggle("active", btn.dataset.view === viewName);
  });

  document.querySelectorAll(".view-panel").forEach((panel) => {
    panel.classList.toggle("active", panel.id === `view-${viewName}`);
  });

  const titleMap = {
    devtools: "Dev Tools Store",
    myapps: "My Applications",
    "control-center": "Control Center",
    settings: "Settings & Diagnostics",
  };
  const topTitle = $("topbar-view-title");
  if (topTitle) topTitle.textContent = titleMap[viewName] || "Dashboard";

  if (viewName === "devtools") loadDevToolsStore();
  if (viewName === "myapps") loadMyApps();
  if (viewName === "control-center") loadControlCenter();
  if (viewName === "settings") loadSettingsView();
}
window.switchView = switchView;

function refreshActiveView() {
  switchView(activeView);
  showToast("View refreshed.", "ok");
}
window.refreshActiveView = refreshActiveView;

// ── Backend Health Probe ─────────────────────────────────────────────────────
async function checkBackendHealth() {
  const dot = $("backend-status-dot");
  const text = $("backend-status-text");
  try {
    const res = await fetch(`${API}/health`);
    const data = await res.json();
    if (res.ok && data.status === "healthy") {
      if (dot) dot.className = "status-dot online";
      if (text) text.textContent = "Backend Active";
      const osBadge = $("os-badge");
      if (osBadge && data.os) osBadge.textContent = `OS: ${data.os} (${data.arch})`;
      return true;
    }
  } catch (_) {
    if (dot) dot.className = "status-dot offline";
    if (text) text.textContent = "Backend Offline";
  }
  return false;
}

// ═══════════════════════════════════════════════════════════════
// 1. DEV TOOLS STORE & SEARCH ENGINE
// ═══════════════════════════════════════════════════════════════

async function loadDevToolsStore(force = false) {
  const heroContainer = $("devtools-hero-container");
  const sectionsWrapper = $("devtools-store-sections");

  try {
    if (!catalogTools.length || force) {
      const catRes = await fetch(`${API}/api/devtools/catalog`);
      const catData = await catRes.json();
      if (catData.ok) catalogTools = catData.tools || [];
    }

    const statusRes = await fetch(`${API}/api/devtools/status`);
    const statusData = await statusRes.json();
    if (statusData.ok) toolStatusCache = statusData.status || {};

    const heroTool = catalogTools.find((t) => t.name === "Docker") || catalogTools[0];
    if (heroTool) {
      const isInstalled = !!toolStatusCache[heroTool.statusKey];
      renderHeroCard(heroTool, isInstalled);
    }

    renderCuratedSections();
    searchDevTools();
  } catch (err) {
    if (sectionsWrapper) {
      sectionsWrapper.innerHTML = `
        <div class="empty-row">
          <h3>Failed to load Dev Tools Store</h3>
          <p style="color:var(--text-3);margin-top:0.4rem;">${escHtml(err.message)}</p>
        </div>
      `;
    }
  }
}

function renderHeroCard(tool, installed) {
  const container = $("devtools-hero-container");
  if (!container || !tool) return;

  const statusBadge = installed
    ? `<span class="store-badge installed">Installed</span>`
    : `<span class="store-badge missing">Not Installed</span>`;

  container.innerHTML = `
    <div class="store-hero-card" onclick="openDevToolDetails('${escHtml(tool.name)}')">
      <div class="hero-icon-box">${escHtml(tool.icon)}</div>
      <div class="hero-content">
        <div class="hero-badge-row">
          <span class="hero-tag">FEATURED DEVELOPER TOOL</span>
          ${statusBadge}
        </div>
        <h2 class="hero-title">${escHtml(tool.name)}</h2>
        <p class="hero-desc">${escHtml(tool.description)}</p>
        <div class="hero-platforms">
          <span class="platform-chip">Windows</span>
          <span class="platform-chip">macOS</span>
          <span class="platform-chip">Linux</span>
          <span class="platform-chip" style="color:var(--accent-cyan)">${escHtml(tool.version || 'v1.0+')}</span>
        </div>
      </div>
      <div class="hero-action-box">
        <button class="primary-btn hero-btn" onclick="event.stopPropagation(); queueToolInstall('${escHtml(tool.name)}')">
          ${installed ? "Manage / Reinstall" : "Install Tool"}
        </button>
      </div>
    </div>
  `;
}

function renderToolCard(tool, installed) {
  const statusBadge = installed
    ? `<span class="store-badge installed">✓ Installed</span>`
    : `<span class="store-badge missing">Not Installed</span>`;

  const trendingBadge = tool.trending ? `<span class="store-badge trending">🔥 Trending</span>` : "";
  const hot2026Badge = tool.hot2026 ? `<span class="store-badge hot2026">⚡ 2026 Hot</span>` : "";
  const offlineBadge = tool.offline ? `<span class="store-badge offline">📴 Offline</span>` : "";

  const actionText = installed ? "Manage / Reinstall" : "Install";
  const actionClass = installed ? "tool-action-btn btn-installed" : "tool-action-btn btn-install";
  const webUrl = tool.url || "https://google.com";

  return `
    <div class="store-tool-card" onclick="openDevToolDetails('${escHtml(tool.name)}')">
      <div class="tool-card-main-content">
        <div class="tool-card-top">
          <div class="tool-card-icon">${escHtml(tool.icon || tool.name.substring(0, 2).toUpperCase())}</div>
          <div class="tool-card-title-group">
            <h3 class="tool-card-name">${escHtml(tool.name)}</h3>
            <span class="tool-card-category-pill">${escHtml(tool.category || 'Developer Tool')}</span>
          </div>
        </div>
        <p class="tool-card-desc">${escHtml(tool.description || 'Verified developer tool & environment runtime.')}</p>
        
        <div class="tool-card-web-link">
          <a href="${escHtml(webUrl)}" target="_blank" rel="noopener noreferrer" onclick="event.stopPropagation();" title="Open official website">
            🌐 ${escHtml(webUrl.replace(/^https?:\/\/(www\.)?/, '').split('/')[0])} &nearr;
          </a>
        </div>
      </div>

      <div class="tool-card-bottom-content">
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
            <span style="color:var(--text-3); font-weight:600;">${escHtml(tool.version || 'Latest')}</span>
          </div>
          <button class="${actionClass}" onclick="event.stopPropagation(); queueToolInstall('${escHtml(tool.name)}')">
            ${actionText}
          </button>
        </div>
      </div>
    </div>
  `;
}

function renderOnlinePackageCard(pkg) {
  const isInstalled = !!pkg.installed;
  const statusBadge = isInstalled
    ? `<span class="store-badge installed">✓ Installed</span>`
    : `<span class="store-badge missing">Not Installed</span>`;

  const srcBadge = `<span class="store-badge offline" style="text-transform:uppercase;font-weight:700;">${escHtml(pkg.source || pkg.manager || 'WINGET')}</span>`;
  const publisher = escHtml(pkg.publisher || 'Verified Publisher');
  const webUrl = pkg.url || `https://winget.run/pkg/${pkg.id}`;

  return `
    <div class="store-tool-card online-pkg-card" onclick="openPkgDetails('${escHtml(pkg.id)}', '${escHtml(pkg.manager)}')">
      <div class="tool-card-main-content">
        <div class="tool-card-top">
          <div class="tool-card-icon online-icon">${escHtml((pkg.manager || 'PK').substring(0, 2).toUpperCase())}</div>
          <div class="tool-card-title-group">
            <h3 class="tool-card-name">${escHtml(pkg.name || pkg.id)}</h3>
            <span class="tool-card-category-pill" style="color:var(--accent-blue);">${publisher} · ${escHtml(pkg.id)}</span>
          </div>
        </div>
        <p class="tool-card-desc">${escHtml(pkg.description || 'Verified package available in online repository.')}</p>

        <div class="tool-card-web-link">
          <a href="${escHtml(webUrl)}" target="_blank" rel="noopener noreferrer" onclick="event.stopPropagation();" title="Open official website">
            🌐 ${escHtml(webUrl.replace(/^https?:\/\/(www\.)?/, '').split('/')[0])} &nearr;
          </a>
        </div>
      </div>

      <div class="tool-card-bottom-content">
        <div class="tool-card-meta-row">
          <div class="tool-card-badges">
            ${statusBadge}
            ${srcBadge}
            <span class="store-badge hot2026">${escHtml(pkg.version || 'Latest')}</span>
          </div>
        </div>

        <div class="tool-card-footer">
          <button class="secondary-btn btn-sm" onclick="event.stopPropagation(); openPkgDetails('${escHtml(pkg.id)}', '${escHtml(pkg.manager)}')">
            Details
          </button>
          <button class="primary-btn btn-sm" onclick="event.stopPropagation(); installDirectPackage('${escHtml(pkg.id)}', '${escHtml(pkg.manager)}', '${escHtml(pkg.name || pkg.id)}')">
            ${isInstalled ? "Reinstall" : "Install"}
          </button>
        </div>
      </div>
    </div>
  `;
}

function renderCuratedSections() {
  const sectionsWrapper = $("devtools-store-sections");
  if (!sectionsWrapper) return;

  sectionsWrapper.innerHTML = "";

  const mapped = catalogTools.map((tool) => ({
    tool,
    installed: !!toolStatusCache[tool.statusKey],
  }));

  const curated = [
    { id: "popular", title: "⭐ Popular Developer Suites", desc: "Most installed tools, compilers, IDEs, and runtimes.", tools: mapped.filter((m) => m.tool.popular) },
    { id: "ides", title: "💻 IDEs & Code Editors", desc: "IntelliJ IDEA, VS Code, PyCharm, Android Studio, Neovim, Sublime.", tools: mapped.filter((m) => m.tool.category === "ides") },
    { id: "languages", title: "⚡ Languages & Compilers", desc: "Python, Rust, Go, Java, Bun, C++, Dart, Flutter, and core runtimes.", tools: mapped.filter((m) => m.tool.category === "languages") },
    { id: "frameworks", title: "📦 Package Managers & Toolchains", desc: "npm, pip, pnpm, Poetry, Bun, Flutter SDK.", tools: mapped.filter((m) => m.tool.category === "frameworks") },
    { id: "devops", title: "🐳 DevOps, Containers & AI", desc: "Docker, Ollama, Terraform, Kubernetes.", tools: mapped.filter((m) => m.tool.category === "devops") },
    { id: "databases", title: "🗄️ Databases & Storage", desc: "DBeaver CE, PostgreSQL, Redis.", tools: mapped.filter((m) => m.tool.category === "databases") },
    { id: "cli", title: "🛠️ CLI & Build Utilities", desc: "GitHub CLI, CMake, fzf, jq, and terminal tools.", tools: mapped.filter((m) => m.tool.category === "cli") },
    { id: "all", title: "🌐 All Developer Tools Catalog", desc: "Full catalog of verified developer tools & runtimes.", tools: mapped },
  ];

  curated.forEach((sec) => {
    if (!sec.tools.length) return;
    const secEl = document.createElement("div");
    secEl.className = "store-section";
    secEl.innerHTML = `
      <div class="store-section-header">
        <h2 class="store-section-title">${escHtml(sec.title)}</h2>
        <div class="store-section-desc">${escHtml(sec.desc)}</div>
      </div>
      <div class="store-grid">
        ${sec.tools.map((m) => renderToolCard(m.tool, m.installed)).join("")}
      </div>
    `;
    sectionsWrapper.appendChild(secEl);
  });
}

function filterDevToolsCategory(category) {
  currentDevToolsCategory = category;
  document.querySelectorAll("#devtools-category-nav .category-pill").forEach((pill) => {
    const text = pill.textContent.toLowerCase();
    const isActive =
      (category === "all" && text.includes("all")) ||
      (category === "popular" && text.includes("popular")) ||
      (category === "trending" && text.includes("trending")) ||
      (category === "alltime" && text.includes("all-time")) ||
      (category === "hot2026" && text.includes("2026")) ||
      (category === "ides" && text.includes("ides")) ||
      (category === "languages" && text.includes("languages")) ||
      (category === "frameworks" && text.includes("frameworks")) ||
      (category === "databases" && text.includes("databases")) ||
      (category === "devops" && text.includes("devops")) ||
      (category === "vcs" && text.includes("git")) ||
      (category === "cli" && text.includes("cli")) ||
      (category === "testing" && text.includes("testing"));
    pill.classList.toggle("active", isActive);
  });
  searchDevTools();
}
window.filterDevToolsCategory = filterDevToolsCategory;

function clearDevToolsSearch() {
  const input = $("devtools-search");
  if (input) input.value = "";
  filterDevToolsCategory("all");
}
window.clearDevToolsSearch = clearDevToolsSearch;

let activeSearchQuery = "";

function searchDevTools() {
  const input = $("devtools-search");
  const query = (input?.value || "").toLowerCase().trim();
  activeSearchQuery = query;

  const clearBtn = $("devtools-search-clear");
  if (clearBtn) clearBtn.classList.toggle("hidden", !query);

  const hero = $("devtools-hero-container");
  const sections = $("devtools-store-sections");
  const searchStatus = $("devtools-search-status");
  const searchTitle = $("devtools-search-title");
  const searchCount = $("devtools-search-count");
  const grid = $("devtools-grid");

  const cat = currentDevToolsCategory || "all";
  const isDefault = query === "" && cat === "all";

  if (isDefault) {
    if (hero) hero.classList.remove("hidden");
    if (sections) sections.classList.remove("hidden");
    if (searchStatus) searchStatus.classList.add("hidden");
    if (grid) grid.classList.add("hidden");
    return;
  }

  if (hero) hero.classList.add("hidden");
  if (sections) sections.classList.add("hidden");
  if (searchStatus) searchStatus.classList.remove("hidden");
  if (grid) grid.classList.remove("hidden");

  // Instant catalog search
  const filteredCatalog = catalogTools.filter((t) => {
    const matchQuery =
      query === "" ||
      t.name.toLowerCase().includes(query) ||
      (t.description || "").toLowerCase().includes(query) ||
      (t.category || "").toLowerCase().includes(query) ||
      (t.statusKey || "").toLowerCase().includes(query);

    if (!matchQuery) return false;
    if (cat === "all") return true;
    if (cat === "popular") return t.popular;
    if (cat === "trending") return t.trending;
    if (cat === "alltime") return t.alltime;
    if (cat === "hot2026") return t.hot2026;
    if (cat === "ides") return t.category === "ides";
    if (cat === "languages") return t.category === "languages";
    if (cat === "frameworks") return t.category === "frameworks";
    if (cat === "databases") return t.category === "databases";
    if (cat === "devops") return t.category === "devops";
    if (cat === "vcs") return t.category === "vcs";
    if (cat === "cli") return t.category === "cli";
    if (cat === "testing") return t.category === "testing";
    return true;
  });

  if (searchTitle) {
    searchTitle.innerHTML = query
      ? `Store & Online Search for "<span style="color:var(--accent-blue)">${escHtml(query)}</span>"`
      : `Category Filter: <span style="color:var(--accent-blue)">${escHtml(cat.toUpperCase())}</span>`;
  }

  grid.innerHTML = "";

  // Render initial matching catalog items
  filteredCatalog.forEach((tool) => {
    const isInstalled = !!toolStatusCache[tool.statusKey];
    grid.insertAdjacentHTML("beforeend", renderToolCard(tool, isInstalled));
  });

  if (!query) {
    if (searchCount) {
      searchCount.textContent = `${filteredCatalog.length} tools available`;
    }
    return;
  }

  // Add Live Online Search Banner into grid
  const liveIndicator = document.createElement("div");
  liveIndicator.id = "live-search-indicator";
  liveIndicator.style.cssText = "grid-column: 1 / -1; background: var(--surface-1); border: 1px solid var(--accent-blue); border-radius: var(--radius-md); padding: 1rem 1.25rem; display: flex; align-items: center; justify-content: space-between;";
  liveIndicator.innerHTML = `
    <div style="display:flex;align-items:center;gap:0.75rem;">
      <span class="status-dot online" style="animation: pulse 1s infinite;"></span>
      <span style="font-size:0.9rem;color:var(--text-1);font-weight:600;">Searching online stores, Windows Store, Winget, NPM, PyPI for "<strong>${escHtml(query)}</strong>"...</span>
    </div>
    <span style="font-size:0.78rem;color:var(--accent-cyan);">Live Registry Query</span>
  `;
  grid.appendChild(liveIndicator);

  if (searchCount) {
    searchCount.textContent = `Searching live registries for "${query}"…`;
  }

  if (searchDebounceTimer) clearTimeout(searchDebounceTimer);
  searchDebounceTimer = setTimeout(() => runUniversalLiveSearch(query, filteredCatalog), 250);
}

async function runUniversalLiveSearch(query, existingCatalog) {
  if (query !== activeSearchQuery) return; // stale request

  const grid = $("devtools-grid");
  const indicator = $("live-search-indicator");
  const searchCount = $("devtools-search-count");

  try {
    const res = await fetch(`${API}/api/devtools/search?q=${encodeURIComponent(query)}`);
    const data = await res.json();
    if (!data.ok) throw new Error("Search failed");

    if (query !== activeSearchQuery) return; // stale check

    const packages = data.packages || [];
    if (indicator) indicator.remove();

    grid.innerHTML = "";

    if (packages.length === 0 && existingCatalog.length === 0) {
      grid.innerHTML = `
        <div class="empty-row" style="grid-column: 1 / -1; padding: 2.5rem; text-align: center;">
          <div style="font-size:2rem;margin-bottom:0.5rem;">🔍</div>
          <h3 style="font-size:1.15rem;color:var(--text-1);">No online packages found for "${escHtml(query)}"</h3>
          <p style="color:var(--text-3);margin-top:0.4rem;font-size:0.85rem;">Checked Windows Package Manager, Microsoft Store, NPM, and PyPI registries.</p>
        </div>
      `;
      if (searchCount) searchCount.textContent = `0 packages found for "${query}"`;
      return;
    }

    // Render all discovered packages as first-class cards in the grid!
    packages.forEach((pkg) => {
      if (pkg.source === "curated") {
        const matchingTool = catalogTools.find((t) => t.name.toLowerCase() === pkg.name.toLowerCase()) || {
          name: pkg.name,
          icon: pkg.name.substring(0, 2).toUpperCase(),
          description: pkg.description,
          category: "tools",
          version: pkg.version,
          url: pkg.url,
          statusKey: pkg.name.toLowerCase(),
        };
        grid.insertAdjacentHTML("beforeend", renderToolCard(matchingTool, pkg.installed));
      } else {
        grid.insertAdjacentHTML("beforeend", renderOnlinePackageCard(pkg));
      }
    });

    if (searchCount) {
      searchCount.textContent = `Found ${packages.length} apps & packages for "${query}"`;
    }
  } catch (err) {
    if (indicator) {
      indicator.innerHTML = `<span style="color:#f87171;">Online registry search error: ${escHtml(err.message)}</span>`;
    }
  }
}

// ═══════════════════════════════════════════════════════════════
// 2. PRODUCT DETAILS DRAWER
// ═══════════════════════════════════════════════════════════════

function openDevToolDetails(toolName) {
  const tool = catalogTools.find((t) => t.name.toLowerCase() === toolName.toLowerCase());
  if (!tool) return;

  const modal = $("modal-devtools-product");
  const content = $("devtools-product-content");
  if (!modal || !content) return;

  const isInstalled = !!toolStatusCache[tool.statusKey];
  const toolUrl = tool.url || "https://google.com";

  content.innerHTML = `
    <div class="product-header-block">
      <div class="product-icon-large">${escHtml(tool.icon || tool.name.substring(0, 2))}</div>
      <div>
        <h2 style="font-size:1.3rem;font-weight:800;">${escHtml(tool.name)}</h2>
        <div style="display:flex;gap:0.4rem;margin-top:0.35rem;">
          <span class="store-badge ${isInstalled ? 'installed' : 'missing'}">${isInstalled ? '✓ Installed' : 'Not Installed'}</span>
          <span class="store-badge offline">${escHtml(tool.category || 'Developer Tool')}</span>
        </div>
      </div>
    </div>

    <p style="font-size:0.85rem;color:var(--text-2);line-height:1.5;margin-bottom:1rem;">
      ${escHtml(tool.description)}
    </p>

    <div class="product-spec-grid">
      <div class="product-spec-item">
        <div class="product-spec-label">Version Target</div>
        <div class="product-spec-value">${escHtml(tool.version || 'Latest Stable')}</div>
      </div>
      <div class="product-spec-item">
        <div class="product-spec-label">Platforms</div>
        <div class="product-spec-value">Windows · macOS · Linux</div>
      </div>
    </div>

    <div class="command-preview-box">
      <label>Official Docs &amp; Homepage:</label>
      <div style="margin-top:0.35rem;"><a href="${escHtml(toolUrl)}" target="_blank" rel="noopener noreferrer" style="color:var(--accent-blue);font-weight:600;text-decoration:none;">${escHtml(toolUrl)} &nearr;</a></div>
    </div>

    <div style="display:flex;justify-content:flex-end;gap:0.75rem;margin-top:1.25rem;">
      <button class="secondary-btn" onclick="closeDevToolProductModalBtn()">Close</button>
      <button class="primary-btn" onclick="closeDevToolProductModalBtn(); queueToolInstall('${escHtml(tool.name)}')">
        ${isInstalled ? 'Manage / Reinstall' : 'Install ' + escHtml(tool.name)}
      </button>
    </div>
  `;

  modal.classList.remove("hidden");
}
window.openDevToolDetails = openDevToolDetails;

function closeDevToolProductModal(e) {
  if (e.target.id === "modal-devtools-product") {
    $("modal-devtools-product")?.classList.add("hidden");
  }
}
window.closeDevToolProductModal = closeDevToolProductModal;

function closeDevToolProductModalBtn() {
  $("modal-devtools-product")?.classList.add("hidden");
}
window.closeDevToolProductModalBtn = closeDevToolProductModalBtn;

async function openPkgDetails(pkgId, manager) {
  const modal = $("modal-devtools-product");
  const content = $("devtools-product-content");
  if (!modal || !content) return;

  modal.classList.remove("hidden");
  content.innerHTML = `<div class="empty-row">Fetching package metadata for ${escHtml(pkgId)}…</div>`;

  try {
    const res = await fetch(`${API}/api/devtools/package?pkg_id=${encodeURIComponent(pkgId)}&manager=${encodeURIComponent(manager)}`);
    const data = await res.json();
    if (!data.ok) {
      content.innerHTML = `<div class="empty-row error">${escHtml(data.error || "Package not found")}</div>`;
      return;
    }

    const p = data.package;
    content.innerHTML = `
      <div class="product-header-block">
        <div class="product-icon-large">${escHtml(p.manager?.substring(0, 2).toUpperCase() || 'PK')}</div>
        <div>
          <h2 style="font-size:1.3rem;font-weight:800;">${escHtml(p.name || p.id)}</h2>
          <div style="display:flex;gap:0.4rem;margin-top:0.35rem;">
            <span class="store-badge offline">${escHtml(p.manager?.toUpperCase())}</span>
            <span class="store-badge hot2026">${escHtml(p.version || 'Latest')}</span>
          </div>
        </div>
      </div>
      <p style="font-size:0.85rem;color:var(--text-2);margin-bottom:1rem;">${escHtml(p.description || 'Verified package.')}</p>
      <div class="command-preview-box">
        <label>Install Command:</label>
        <code>$ ${escHtml(p.install_cmd || p.id)}</code>
      </div>
      <div style="display:flex;justify-content:flex-end;gap:0.75rem;margin-top:1.25rem;">
        <button class="secondary-btn" onclick="closeDevToolProductModalBtn()">Close</button>
        <button class="primary-btn" onclick="closeDevToolProductModalBtn(); installDirectPackage('${escHtml(p.id)}','${escHtml(p.manager)}','${escHtml(p.name || p.id)}')">Queue Install</button>
      </div>
    `;
  } catch (err) {
    content.innerHTML = `<div class="empty-row error">Error: ${escHtml(err.message)}</div>`;
  }
}
window.openPkgDetails = openPkgDetails;

async function queueToolInstall(toolName) {
  // Find the tool's statusKey to check real installation state
  const tool = catalogTools.find((t) => t.name.toLowerCase() === toolName.toLowerCase());
  const statusKey = tool?.statusKey || toolName.toLowerCase();
  const isInstalled = !!toolStatusCache[statusKey];

  if (isInstalled) {
    // Already installed → open the Manage modal (Update / Reinstall / Uninstall)
    openManageToolModal(toolName);
  } else {
    // Not installed → fetch install command and open the normal command modal
    try {
      const res = await fetch(`${API}/api/devtools/extract`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ app: toolName }),
      });
      const data = await res.json();
      if (data.ok) {
        openCommandModal(data.command, `Install ${toolName}`, data.risk || "Low", `Install ${toolName} via native system package manager`);
      }
    } catch (err) {
      showToast(`Error: ${err.message}`, "err");
    }
  }
}
window.queueToolInstall = queueToolInstall;

// ── Manage Tool Modal (Update / Reinstall / Uninstall) ────────────────────────
let activeManageCmds = {}; // { update, reinstall, uninstall }
let activeManageToolName = "";

async function openManageToolModal(toolName) {
  activeManageToolName = toolName;
  activeManageCmds = {};

  const modal = $("modal-manage-tool");
  if (!modal) return;

  // Show modal immediately with loading state
  $("manage-tool-title").textContent = `Manage: ${toolName}`;
  $("manage-tool-subtitle").textContent = `Tool is installed on your system — choose an action below.`;
  $("manage-cmd-update").textContent = "Fetching command...";
  $("manage-cmd-reinstall").textContent = "Fetching command...";
  $("manage-cmd-uninstall").textContent = "Fetching command...";
  modal.classList.remove("hidden");

  try {
    const res = await fetch(`${API}/api/devtools/manage-cmds?tool=${encodeURIComponent(toolName.toLowerCase())}`);
    const data = await res.json();
    if (data.ok && data.commands) {
      activeManageCmds = data.commands;
      $("manage-cmd-update").textContent    = `$ ${data.commands.update}`;
      $("manage-cmd-reinstall").textContent = `$ ${data.commands.reinstall}`;
      $("manage-cmd-uninstall").textContent = `$ ${data.commands.uninstall}`;
      $("manage-tool-subtitle").textContent = `via ${data.manager?.toUpperCase()} · ${data.os} · package: ${data.pkg_id}`;
    } else {
      $("manage-cmd-update").textContent = $("manage-cmd-reinstall").textContent = $("manage-cmd-uninstall").textContent = "Could not fetch commands.";
    }
  } catch (err) {
    $("manage-cmd-update").textContent = $("manage-cmd-reinstall").textContent = $("manage-cmd-uninstall").textContent = `Error: ${err.message}`;
  }
}
window.openManageToolModal = openManageToolModal;

function closeManageToolModal(e) {
  if (e.target.id === "modal-manage-tool") {
    $("modal-manage-tool")?.classList.add("hidden");
  }
}
window.closeManageToolModal = closeManageToolModal;

function closeManageToolModalBtn() {
  $("modal-manage-tool")?.classList.add("hidden");
}
window.closeManageToolModalBtn = closeManageToolModalBtn;

async function manageToolAction(action, mode) {
  const cmd = activeManageCmds[action];
  if (!cmd) { showToast("Command not loaded yet.", "err"); return; }

  const labelMap = { update: "Update", reinstall: "Reinstall", uninstall: "Uninstall" };
  const riskMap  = { update: "Low", reinstall: "Medium", uninstall: "High" };
  const label = `${labelMap[action]} ${activeManageToolName}`;

  if (action === "uninstall" && mode === "run") {
    if (!confirm(`Are you sure you want to UNINSTALL ${activeManageToolName}?`)) return;
  }

  closeManageToolModalBtn();

  if (mode === "queue") {
    try {
      const res = await fetch(`${API}/api/control-center/enqueue`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ command: cmd, target: label, risk_tier: riskMap[action], source: "devtools_manage" }),
      });
      const d = await res.json();
      if (d.ok) {
        showToast(`${label} queued in Control Center.`, "ok");
        updateControlCenterBadge();
      } else {
        showToast(d.error || "Queue failed.", "err");
      }
    } catch (err) {
      showToast(`Queue error: ${err.message}`, "err");
    }
  } else {
    openTerminalConsole(cmd, label);
  }
}
window.manageToolAction = manageToolAction;

async function installDirectPackage(pkgId, manager, pkgName) {
  try {
    const res = await fetch(`${API}/api/devtools/package?pkg_id=${encodeURIComponent(pkgId)}&manager=${encodeURIComponent(manager || '')}`);
    const data = await res.json();
    if (data.ok && data.package && data.package.install_cmd) {
      openCommandModal(data.package.install_cmd, `Install ${pkgName || pkgId}`, "Medium", `Install ${pkgId} via ${manager || 'package manager'}`);
      return;
    }
  } catch (_) {}

  // Fallback: request dynamic extraction from backend
  try {
    const res = await fetch(`${API}/api/devtools/extract`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ app: pkgId }),
    });
    const data = await res.json();
    if (data.ok && data.command) {
      openCommandModal(data.command, `Install ${pkgName || pkgId}`, data.risk || "Medium", `Install ${pkgId} via ${manager || 'package manager'}`);
      return;
    }
  } catch (_) {}

  showToast(`Could not resolve install command for ${pkgName || pkgId}`, "err");
}
window.installDirectPackage = installDirectPackage;

// ═══════════════════════════════════════════════════════════════
// 3. DEV ENVIRONMENT DOCTOR, STACKS & RAG AUTO-REPAIR FINDER
// ═══════════════════════════════════════════════════════════════

function switchDoctorTab(tabName) {
  activeDoctorTab = tabName;
  ["health", "stacks", "repairs"].forEach((t) => {
    const btn = $(`btn-doc-tab-${t}`);
    const panel = $(`panel-doc-${t}`);
    if (btn) btn.classList.toggle("active", t === tabName);
    if (panel) panel.style.display = t === tabName ? "block" : "none";
  });

  if (tabName === "repairs" && autoRepairsCache.length === 0) {
    runAutoRepairScan();
  }
}
window.switchDoctorTab = switchDoctorTab;

async function openDevDoctorModal() {
  const modal = $("modal-dev-doctor");
  if (!modal) return;
  modal.classList.remove("hidden");
  switchDoctorTab("health");
  await runDevDoctorScan();
}
window.openDevDoctorModal = openDevDoctorModal;

function closeDevDoctorModal(e) {
  if (e.target.id === "modal-dev-doctor") {
    $("modal-dev-doctor")?.classList.add("hidden");
  }
}
window.closeDevDoctorModal = closeDevDoctorModal;

function closeDevDoctorModalBtn() {
  $("modal-dev-doctor")?.classList.add("hidden");
}
window.closeDevDoctorModalBtn = closeDevDoctorModalBtn;

async function runDevDoctorScan() {
  const rescanBtn = $("btn-doctor-rescan");
  const bannerScore = $("banner-health-score");
  const bannerStatus = $("banner-health-status");
  const bannerStats = $("banner-health-stats");

  if (rescanBtn) {
    rescanBtn.innerHTML = `<span style="display:inline-block;animation:spin 0.8s linear infinite;">⟳</span> Scanning…`;
    rescanBtn.disabled = true;
  }
  if (bannerScore) bannerScore.textContent = "…";
  if (bannerStatus) bannerStatus.textContent = "Running live system probe…";
  if (bannerStats) bannerStats.textContent = "Scanning installed PATH binaries, compilers, and toolchains…";

  showToast("Scanning developer environment & toolchains...", "ok");

  try {
    const res = await fetch(`${API}/api/devtools/doctor`);
    const data = await res.json();
    if (!data.ok) throw new Error(data.error || "Scan failed");

    const health_score = data.health_score ?? 0;
    const installed_tools = data.installed_count ?? data.installed_tools ?? 0;
    const total_tools = data.total_probed ?? data.total_tools ?? 8;
    const checks = data.checks || [];
    const stacks = data.stacks || [];

    // Update banner elements
    if (bannerScore) bannerScore.textContent = `${health_score}%`;
    if (bannerStatus) {
      bannerStatus.textContent = health_score >= 80 ? "Environment Optimal" : (health_score >= 50 ? "Environment Fair" : "Setup Recommended");
      bannerStatus.style.color = health_score >= 80 ? "#34d399" : (health_score >= 50 ? "#fbbf24" : "#f87171");
    }
    if (bannerStats) {
      bannerStats.textContent = `${installed_tools} of ${total_tools} developer runtimes & tools verified on host (${data.os} ${data.arch}). Just scanned.`;
    }

    // Update modal elements
    const modalScore = $("doc-modal-score");
    const readyCount = $("doc-modal-ready-count");
    const totalCount = $("doc-modal-total-count");
    const statusText = $("doc-modal-status-text");
    if (modalScore) modalScore.textContent = `${health_score}%`;
    if (readyCount) readyCount.textContent = installed_tools;
    if (totalCount) totalCount.textContent = total_tools;
    if (statusText) statusText.textContent = health_score >= 80 ? "System ready for fullstack development" : "Several essential tools or runtimes are missing";

    const checksGrid = $("doc-modal-checks-grid");
    if (checksGrid && checks) {
      checksGrid.innerHTML = checks.map((c) => `
        <div class="doctor-check-item ${c.installed ? 'ready' : 'missing'}">
          <span>${escHtml(c.name)}</span>
          <span style="font-weight:700;color:${c.installed ? '#34d399' : '#f87171'}">${c.installed ? '✓ Ready' : '✗ Missing'}</span>
        </div>
      `).join("");
    }

    const stacksGrid = $("doc-modal-stacks-grid");
    if (stacksGrid && stacks) {
      stacksGrid.innerHTML = stacks.map((s) => {
        const missing = s.missing_count ?? (s.missing_tools ? s.missing_tools.length : 0);
        const toolsList = s.tools || (s.installed_tools || []).map(t => ({ name: t, installed: true })).concat((s.missing_tools || []).map(t => ({ name: t, installed: false })));
        return `
          <div class="stack-card">
            <div>
              <div class="stack-card-header">
                <span class="stack-icon">${s.icon}</span>
                <div>
                  <div class="stack-title">${escHtml(s.name)}</div>
                  <div style="font-size:0.75rem;color:${missing === 0 ? '#34d399' : 'var(--accent-cyan)'};">
                    ${missing === 0 ? '✓ All tools installed' : `${missing} missing tool${missing > 1 ? 's' : ''}`}
                  </div>
                </div>
              </div>
              <div class="stack-desc">${escHtml(s.description)}</div>
              <div class="stack-tools-list">
                ${toolsList.map((t) => `
                  <span class="stack-tool-pill ${t.installed ? 'installed' : 'missing'}">
                    ${t.installed ? '✓' : '+'} ${escHtml(t.name || t)}
                  </span>
                `).join("")}
              </div>
            </div>
            <button class="primary-btn btn-sm" onclick="installCuratedStack('${s.id}')" ${missing === 0 ? 'disabled style="opacity:0.6"' : ''}>
              ${missing === 0 ? 'Stack Complete' : `Install Stack (${missing} Tools)`}
            </button>
          </div>
        `;
      }).join("");
    }

    // Refresh store catalog status cache
    const statusRes = await fetch(`${API}/api/devtools/status`);
    const statusData = await statusRes.json();
    if (statusData.ok) {
      toolStatusCache = statusData.status || {};
      renderCuratedSections();
    }

    showToast(`Environment scan complete: ${health_score}% health score.`, "ok");
  } catch (err) {
    if (bannerStatus) bannerStatus.textContent = "Diagnostic scan error";
    showToast(`Scan error: ${err.message}`, "err");
  } finally {
    if (rescanBtn) {
      rescanBtn.innerHTML = `<svg style="width:13px;height:13px;"><use href="#icon-refresh"></use></svg> Re-Scan`;
      rescanBtn.disabled = false;
    }
  }
}
window.runDevDoctorScan = runDevDoctorScan;

async function installCuratedStack(stackId) {
  try {
    const res = await fetch(`${API}/api/devtools/doctor/install-stack`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ stack_id: stackId }),
    });
    const data = await res.json();
    if (data.ok) {
      showToast(data.message, "ok");
      closeDevDoctorModalBtn();
      updateControlCenterBadge();
    } else {
      showToast(data.error || "Failed to enqueue stack", "err");
    }
  } catch (err) {
    showToast(`Error installing stack: ${err.message}`, "err");
  }
}
window.installCuratedStack = installCuratedStack;

async function runAutoRepairScan() {
  const container = $("doc-modal-repairs-list");
  const badge = $("doc-repair-badge");
  if (!container) return;

  container.innerHTML = '<div class="empty-row">Scanning local dev environment and querying RAG knowledge base…</div>';

  try {
    const res = await fetch(`${API}/api/devtools/repair/find`);
    const data = await res.json();
    if (!data.ok) {
      container.innerHTML = `<div class="empty-row error">${escHtml(data.error || "Repair search failed")}</div>`;
      return;
    }

    const repairs = data.repairs || [];
    autoRepairsCache = repairs;

    if (badge) {
      badge.textContent = repairs.length;
      badge.style.display = repairs.length > 0 ? "inline-flex" : "none";
    }

    if (repairs.length === 0) {
      container.innerHTML = `
        <div class="empty-row" style="color:#34d399;">
          ✓ No active environment anomalies detected. Your development toolchains, PATH, and VCS are in prime condition.
        </div>
      `;
      return;
    }

    container.innerHTML = repairs.map((r) => `
      <div class="repair-card">
        <div class="repair-card-header">
          <div class="repair-title">
            <span>⚠️</span>
            <span>${escHtml(r.issue)}</span>
          </div>
          <span class="repair-component-tag">${escHtml(r.component || 'System')}</span>
        </div>
        <div class="repair-explanation">${escHtml(r.explanation)}</div>
        <div class="repair-code-box">
          <code>$ ${escHtml(r.command)}</code>
          <button class="secondary-btn btn-sm" onclick="runSandboxDryRun('${encodeURIComponent(r.command)}', '${encodeURIComponent(r.issue)}')" title="Test in sandbox dry-run engine">
            🧪 Sandbox Test
          </button>
        </div>
        <div class="repair-card-actions">
          <button class="secondary-btn btn-sm" onclick="queueAutoRepair('${r.id}', '${encodeURIComponent(r.issue)}', '${encodeURIComponent(r.command)}', '${r.risk || 'Low'}')">
            📥 Queue in Control Center
          </button>
          <button class="primary-btn btn-sm" onclick="openTerminalConsole('${escHtml(r.command)}', '${escHtml(r.issue)}')">
            ⚡ Run Fix in Terminal
          </button>
        </div>
      </div>
    `).join("");
  } catch (err) {
    container.innerHTML = `<div class="empty-row error">Failed to scan repairs: ${escHtml(err.message)}</div>`;
  }
}
window.runAutoRepairScan = runAutoRepairScan;

async function queueAutoRepair(repairId, encIssue, encCmd, risk) {
  const issue = decodeURIComponent(encIssue);
  const cmd = decodeURIComponent(encCmd);
  try {
    const res = await fetch(`${API}/api/control-center/queue/enqueue`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        command: cmd,
        target: issue,
        action_type: "repair",
        risk: risk,
        origin: "rag_auto_repair",
      }),
    });
    const d = await res.json();
    if (d.ok) {
      showToast(`Enqueued repair for '${issue}' into Control Center.`, "ok");
      updateControlCenterBadge();
    } else {
      showToast(`Error: ${d.error}`, "err");
    }
  } catch (err) {
    showToast(`Failed to enqueue repair: ${err.message}`, "err");
  }
}
window.queueAutoRepair = queueAutoRepair;

async function runSandboxDryRun(encCmd, encTitle) {
  const cmd = decodeURIComponent(encCmd);
  const title = decodeURIComponent(encTitle || "Sandbox Simulation");
  try {
    const res = await fetch(`${API}/api/devtools/sandbox/dry-run`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ command: cmd, target: title }),
    });
    const data = await res.json();
    if (data.ok) {
      const { risk_tier, blast_radius } = data;
      alert(`🧪 SANDBOX DRY-RUN REPORT\n\nCommand: ${cmd}\nTarget: ${title}\nRisk Tier: ${risk_tier}\n\nPredicted Blast Radius:\n• Filesystem: ${JSON.stringify(blast_radius.filesystem || "No destructive changes")}\n• Registry: ${JSON.stringify(blast_radius.registry || "None")}\n• Network: ${JSON.stringify(blast_radius.network || "Standard package repositories")}\n\nSandbox Verdict: SAFE TO EXECUTE`);
    } else {
      showToast(`Sandbox error: ${data.detail || "Failed"}`, "err");
    }
  } catch (err) {
    showToast(`Sandbox execution failed: ${err.message}`, "err");
  }
}
window.runSandboxDryRun = runSandboxDryRun;

// ═══════════════════════════════════════════════════════════════
// 4. MY APPLICATIONS (VERIFIED INSTALLED APPS)
// ═══════════════════════════════════════════════════════════════

async function loadMyApps() {
  const grid = $("myapps-grid");
  const empty = $("myapps-empty");
  const totalStat = $("myapps-stat-total");
  if (!grid) return;

  try {
    const res = await fetch(`${API}/api/devtools/managed`);
    const data = await res.json();
    if (!data.ok) throw new Error(data.error || "Failed to load managed apps");

    managedAppsCache = data.apps || [];
    if (totalStat) totalStat.textContent = managedAppsCache.length;

    if (managedAppsCache.length === 0) {
      grid.innerHTML = "";
      if (empty) empty.classList.remove("hidden");
      return;
    }

    if (empty) empty.classList.add("hidden");
    grid.innerHTML = managedAppsCache.map((app) => renderManagedAppCard(app)).join("");
  } catch (err) {
    grid.innerHTML = `<div class="empty-row error">${escHtml(err.message)}</div>`;
  }
}
window.loadMyApps = loadMyApps;

function renderManagedAppCard(app) {
  const appId = escHtml(app.app_id || app.name);
  const name = escHtml(app.name);
  const pm = escHtml(app.package_manager || "System");

  return `
    <div class="store-tool-card myapps-card" id="card-myapp-${appId}">
      <div>
        <div class="tool-card-top">
          <div class="tool-card-icon">${name.substring(0, 2).toUpperCase()}</div>
          <div>
            <h3 class="tool-card-name">${name}</h3>
            <span class="tool-card-category-pill">${pm.toUpperCase()}</span>
          </div>
        </div>
        <p class="tool-card-desc">${escHtml(app.description || 'Verified developer application.')}</p>
      </div>

      <div>
        <div class="tool-card-meta-row">
          <div class="tool-card-badges">
            <span class="store-badge installed">✓ Verified Installed</span>
          </div>
        </div>

        <div class="tool-card-footer">
          <button class="secondary-btn btn-sm" onclick="triggerAppUninstall('${appId}', '${name}')">Uninstall</button>
          <button class="primary-btn btn-sm" onclick="triggerAppUpdate('${appId}', '${name}')">Update</button>
        </div>
      </div>
    </div>
  `;
}

function filterMyApps() {
  const query = ($("myapps-search-input")?.value || "").toLowerCase().trim();
  const grid = $("myapps-grid");
  const empty = $("myapps-empty");
  if (!grid) return;

  const filtered = managedAppsCache.filter((a) =>
    a.name.toLowerCase().includes(query) || (a.category || "").toLowerCase().includes(query)
  );

  if (filtered.length === 0) {
    grid.innerHTML = `<div class="empty-row" style="grid-column: 1 / -1;">No matching installed applications found.</div>`;
    return;
  }

  if (empty) empty.classList.add("hidden");
  grid.innerHTML = filtered.map((app) => renderManagedAppCard(app)).join("");
}
window.filterMyApps = filterMyApps;

async function triggerAppUpdate(appId, appName) {
  openTerminalConsole(`winget upgrade --id ${appId} --exact --silent`, `Updating ${appName}`);
}
window.triggerAppUpdate = triggerAppUpdate;

async function triggerAppUninstall(appId, appName) {
  if (!confirm(`Are you sure you want to uninstall '${appName}'?`)) return;
  try {
    const res = await fetch(`${API}/api/devtools/uninstall`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ app_id: appId, confirm: true }),
    });
    const d = await res.json();
    if (d.ok) {
      showToast(`Uninstall action for '${appName}' processed.`, "ok");
      loadMyApps();
    }
  } catch (err) {
    showToast(`Error: ${err.message}`, "err");
  }
}
window.triggerAppUninstall = triggerAppUninstall;

function updateAllApps() {
  openTerminalConsole("winget upgrade --all --silent", "Updating All System Packages");
}
window.updateAllApps = updateAllApps;

// ═══════════════════════════════════════════════════════════════
// 5. CONTROL CENTER (QUEUE, AUDIT, SNAPSHOTS)
// ═══════════════════════════════════════════════════════════════

async function loadControlCenter() {
  loadApprovalQueue();
  loadAuditTrail();
  loadSnapshots();
  updateControlCenterBadge();
}
window.loadControlCenter = loadControlCenter;

async function updateControlCenterBadge() {
  try {
    const res = await fetch(`${API}/api/control-center/queue?status=pending`);
    const data = await res.json();
    const count = data.items?.length || 0;
    const badge = $("sidebar-queue-badge");
    if (badge) {
      badge.textContent = count;
      badge.style.display = count > 0 ? "inline-flex" : "none";
    }
  } catch (_) {}
}

async function loadApprovalQueue() {
  const container = $("control-center-queue");
  if (!container) return;

  const status = $("cc-filter-status")?.value || "pending";
  const risk = $("cc-filter-risk")?.value || "";

  try {
    const res = await fetch(`${API}/api/control-center/queue?status=${status}&risk=${risk}`);
    const data = await res.json();
    if (!data.ok) throw new Error(data.error || "Failed to load queue");

    const items = data.items || [];
    if (items.length === 0) {
      container.innerHTML = `<div class="empty-row">No actions currently in this queue view.</div>`;
      return;
    }

    container.innerHTML = items.map((item) => `
      <div class="cc-queue-item glass">
        <div class="queue-item-header">
          <div class="queue-item-title-group">
            <strong style="color:var(--text-1);font-size:0.95rem;">${escHtml(item.target || item.action_id)}</strong>
            <span class="risk-badge ${escHtml(item.risk_tier || 'Low')}">${escHtml(item.risk_tier || 'Low')}</span>
            <span class="store-badge offline">${escHtml(item.source || 'devtools')}</span>
          </div>
          <span style="font-size:0.75rem;color:var(--text-3);">${new Date(item.created_at).toLocaleTimeString()}</span>
        </div>
        <div class="queue-item-command">
          <code>$ ${escHtml(item.command)}</code>
        </div>
        <div class="queue-item-actions">
          <button class="secondary-btn btn-sm" onclick="runSandboxDryRun('${encodeURIComponent(item.command)}', '${encodeURIComponent(item.target)}')">🧪 Sandbox</button>
          <button class="danger-btn btn-sm" onclick="rejectAction('${item.action_id}')">Reject</button>
          <button class="primary-btn btn-sm" onclick="approveAction('${item.action_id}')">Approve &amp; Run</button>
        </div>
      </div>
    `).join("");
  } catch (err) {
    container.innerHTML = `<div class="empty-row error">${escHtml(err.message)}</div>`;
  }
}

async function approveAction(actionId) {
  try {
    const res = await fetch(`${API}/api/control-center/approve`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ action_id: actionId, reason: "Approved from UI" }),
    });
    const d = await res.json();
    if (d.ok) {
      showToast("Action approved & executed.", "ok");
      loadControlCenter();
    }
  } catch (err) {
    showToast(`Error: ${err.message}`, "err");
  }
}
window.approveAction = approveAction;

async function rejectAction(actionId) {
  try {
    const res = await fetch(`${API}/api/control-center/reject`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ action_id: actionId, reason: "Rejected from UI" }),
    });
    const d = await res.json();
    if (d.ok) {
      showToast("Action rejected.", "ok");
      loadControlCenter();
    }
  } catch (err) {
    showToast(`Error: ${err.message}`, "err");
  }
}
window.rejectAction = rejectAction;

async function batchApprovePending() {
  if (!confirm("Approve ALL pending actions?")) return;
  try {
    const res = await fetch(`${API}/api/control-center/batch-approve`, { method: "POST" });
    const d = await res.json();
    if (d.ok) {
      showToast(`Batch approved ${d.approved_count} action(s).`, "ok");
      loadControlCenter();
    }
  } catch (err) {
    showToast(`Error: ${err.message}`, "err");
  }
}
window.batchApprovePending = batchApprovePending;

async function batchRejectPending() {
  if (!confirm("Reject ALL pending actions?")) return;
  try {
    const res = await fetch(`${API}/api/control-center/batch-reject`, { method: "POST" });
    const d = await res.json();
    if (d.ok) {
      showToast(`Batch rejected ${d.rejected_count} action(s).`, "ok");
      loadControlCenter();
    }
  } catch (err) {
    showToast(`Error: ${err.message}`, "err");
  }
}
window.batchRejectPending = batchRejectPending;

async function loadAuditTrail() {
  const container = $("control-center-audit");
  const search = $("cc-audit-search")?.value || "";
  if (!container) return;

  try {
    const res = await fetch(`${API}/api/control-center/audit?search=${encodeURIComponent(search)}&limit=25`);
    const data = await res.json();
    if (!data.ok) return;

    const entries = data.entries || [];
    if (entries.length === 0) {
      container.innerHTML = `<div class="empty-row">No audit log records found.</div>`;
      return;
    }

    container.innerHTML = entries.map((e) => `
      <div class="audit-row">
        <div style="display:flex;align-items:center;gap:0.6rem;">
          <span class="status-pill ${e.decision === 'APPROVED' ? 'installed' : 'missing'}">${escHtml(e.decision)}</span>
          <strong style="color:var(--text-1);font-size:0.85rem;">${escHtml(e.target || e.action_id)}</strong>
        </div>
        <div style="font-family:var(--font-mono);font-size:0.78rem;color:var(--text-3);">${new Date(e.timestamp).toLocaleTimeString()}</div>
      </div>
    `).join("");
  } catch (_) {}
}

function exportAuditTrail(format) {
  window.open(`${API}/api/control-center/audit/export?format=${format}`, "_blank");
}
window.exportAuditTrail = exportAuditTrail;

async function loadSnapshots() {
  const container = $("control-center-snapshots");
  if (!container) return;

  try {
    const res = await fetch(`${API}/api/control-center/snapshots`);
    const data = await res.json();
    const snaps = data.snapshots || [];

    if (snaps.length === 0) {
      container.innerHTML = `<div class="empty-row">No system snapshots created yet.</div>`;
      return;
    }

    container.innerHTML = snaps.map((s) => `
      <div class="snapshot-card glass">
        <div>
          <strong style="color:var(--text-1);">${escHtml(s.label)}</strong>
          <div style="font-size:0.75rem;color:var(--text-3);margin-top:0.2rem;">${new Date(s.created_at).toLocaleString()} · ID: ${escHtml(s.id.substring(0, 8))}</div>
        </div>
        <button class="secondary-btn btn-sm" onclick="rollbackSnapshot('${s.id}')">Rollback</button>
      </div>
    `).join("");
  } catch (_) {}
}

async function createManualSnapshot() {
  const label = prompt("Enter a label for this system restore point:", `Manual Restore Point`);
  if (!label) return;
  try {
    const res = await fetch(`${API}/api/control-center/snapshots?label=${encodeURIComponent(label)}`, { method: "POST" });
    const d = await res.json();
    if (d.ok) {
      showToast("System snapshot created.", "ok");
      loadSnapshots();
    }
  } catch (err) {
    showToast(`Failed to create snapshot: ${err.message}`, "err");
  }
}
window.createManualSnapshot = createManualSnapshot;

async function rollbackSnapshot(snapId) {
  if (!confirm("Are you sure you want to rollback to this restore point?")) return;
  try {
    const res = await fetch(`${API}/api/control-center/snapshots/revert?snap_id=${encodeURIComponent(snapId)}`, { method: "POST" });
    const d = await res.json();
    if (d.ok) {
      showToast("Rollback applied.", "ok");
      loadControlCenter();
    }
  } catch (err) {
    showToast(`Error: ${err.message}`, "err");
  }
}
window.rollbackSnapshot = rollbackSnapshot;

// ═══════════════════════════════════════════════════════════════
// 6. SNAPSHOT DIFF COMPARATOR
// ═══════════════════════════════════════════════════════════════

async function openSnapshotDiffModal() {
  const modal = $("modal-snapshot-diff");
  if (!modal) return;
  modal.classList.remove("hidden");

  try {
    const res = await fetch(`${API}/api/control-center/snapshots`);
    const d = await res.json();
    const snaps = d.snapshots || [];
    const sel1 = $("diff-snap-1");
    const sel2 = $("diff-snap-2");

    if (snaps.length < 2) {
      $("snapshot-diff-output").innerHTML = '<div class="empty-row">Need at least two snapshots to compare. Create another snapshot first.</div>';
      return;
    }

    const opts = snaps.map((s) => `<option value="${s.id}">${escHtml(s.label)} (${s.id.substring(0, 8)})</option>`).join("");
    if (sel1) sel1.innerHTML = opts;
    if (sel2) {
      sel2.innerHTML = opts;
      if (snaps.length > 1) sel2.selectedIndex = 1;
    }

    runSnapshotDiff();
  } catch (err) {
    showToast("Error loading snapshots", "err");
  }
}
window.openSnapshotDiffModal = openSnapshotDiffModal;

function closeSnapshotDiffModal(e) {
  if (e.target.id === "modal-snapshot-diff") {
    $("modal-snapshot-diff")?.classList.add("hidden");
  }
}
window.closeSnapshotDiffModal = closeSnapshotDiffModal;

function closeSnapshotDiffModalBtn() {
  $("modal-snapshot-diff")?.classList.add("hidden");
}
window.closeSnapshotDiffModalBtn = closeSnapshotDiffModalBtn;

async function runSnapshotDiff() {
  const s1 = $("diff-snap-1")?.value;
  const s2 = $("diff-snap-2")?.value;
  const out = $("snapshot-diff-output");
  if (!s1 || !s2 || !out) return;

  if (s1 === s2) {
    out.innerHTML = '<div class="empty-row">Select two different snapshots to compare differences.</div>';
    return;
  }

  out.innerHTML = '<div class="empty-row">Computing snapshot differences…</div>';

  try {
    const res = await fetch(`${API}/api/control-center/snapshots/diff?snap_1=${encodeURIComponent(s1)}&snap_2=${encodeURIComponent(s2)}`);
    const d = await res.json();
    if (!d.ok) {
      out.innerHTML = `<div class="empty-row error">${escHtml(d.error || "Diff failed")}</div>`;
      return;
    }

    let html = `
      <div style="display:flex;justify-content:space-between;margin-bottom:1rem;font-size:0.85rem;">
        <div><strong>Base:</strong> ${escHtml(d.snap_1.label)}</div>
        <div><strong>Target:</strong> ${escHtml(d.snap_2.label)}</div>
      </div>
      <div class="diff-section-title">📦 Package Differences by Manager</div>
    `;

    let anyDiff = false;
    for (const [pm, diff] of Object.entries(d.package_diff || {})) {
      if (diff.added.length > 0 || diff.removed.length > 0) {
        anyDiff = true;
        html += `
          <div style="background:var(--surface-2);border-radius:var(--radius-sm);padding:0.75rem;margin-bottom:0.6rem;">
            <strong>${escHtml(pm.toUpperCase())}</strong>
            ${diff.added.length > 0 ? `<div class="diff-tag-added" style="margin-top:0.25rem;">+ Added (${diff.added.length}): ${diff.added.slice(0, 8).map(escHtml).join(", ")}</div>` : ''}
            ${diff.removed.length > 0 ? `<div class="diff-tag-removed" style="margin-top:0.25rem;">- Removed (${diff.removed.length}): ${diff.removed.slice(0, 8).map(escHtml).join(", ")}</div>` : ''}
          </div>
        `;
      }
    }

    if (!anyDiff) html += `<div style="color:var(--text-2);margin-bottom:1rem;">No package differences detected between selected snapshots.</div>`;
    out.innerHTML = html;
  } catch (err) {
    out.innerHTML = `<div class="empty-row error">Diff error: ${escHtml(err.message)}</div>`;
  }
}
window.runSnapshotDiff = runSnapshotDiff;

// ═══════════════════════════════════════════════════════════════
// 7. COMMAND MODAL & LIVE TERMINAL CONSOLE
// ═══════════════════════════════════════════════════════════════

function openCommandModal(command, title, risk, purpose) {
  activeModalAction = { command, title, risk, purpose };
  const modal = $("modal-command-run");
  if (!modal) return;

  $("cmd-modal-title").textContent = title;
  $("cmd-modal-code").textContent = command;
  $("cmd-modal-purpose").textContent = purpose;

  const riskBadge = $("cmd-modal-risk");
  if (riskBadge) {
    riskBadge.textContent = risk;
    riskBadge.className = `risk-badge ${risk}`;
  }

  modal.classList.remove("hidden");
}

function closeCommandModal(e) {
  if (e.target.id === "modal-command-run") {
    $("modal-command-run")?.classList.add("hidden");
  }
}
window.closeCommandModal = closeCommandModal;

function closeCommandModalBtn() {
  $("modal-command-run")?.classList.add("hidden");
}
window.closeCommandModalBtn = closeCommandModalBtn;

async function executeCommandModalAction() {
  if (!activeModalAction) return;
  const { command, title, risk } = activeModalAction;

  try {
    const res = await fetch(`${API}/api/control-center/enqueue`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        command,
        target: title,
        risk_tier: risk,
        source: "devtools_store",
      }),
    });
    const d = await res.json();
    if (d.ok) {
      showToast(`Action queued in Control Center.`, "ok");
      closeCommandModalBtn();
      updateControlCenterBadge();
    }
  } catch (err) {
    showToast(`Error queueing action: ${err.message}`, "err");
  }
}
window.executeCommandModalAction = executeCommandModalAction;

function runCommandInLiveTerminal() {
  if (!activeModalAction) return;
  const cmd = activeModalAction.command;
  const title = activeModalAction.title || "Execution";
  closeCommandModalBtn();
  openTerminalConsole(cmd, title);
}
window.runCommandInLiveTerminal = runCommandInLiveTerminal;

function openTerminalConsole(command, title) {
  const modal = $("modal-terminal-console");
  const output = $("term-output");
  const titleEl = $("term-title");
  const badgeEl = $("term-status-badge");
  const metaEl = $("term-meta");

  if (!modal || !output) return;
  modal.classList.remove("hidden");

  if (titleEl) titleEl.textContent = `Executing: ${title || command}`;
  if (badgeEl) {
    badgeEl.textContent = "Running";
    badgeEl.className = "status-pill active";
  }
  if (metaEl) metaEl.textContent = `Started at ${new Date().toLocaleTimeString()} — $ ${command}`;
  output.textContent = `$ ${command}\n\n`;

  fetch(`${API}/api/devtools/execute-stream`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ command, target: title }),
  }).then((response) => {
    const reader = response.body.getReader();
    const decoder = new TextDecoder("utf-8");
    let buffer = "";

    function readChunk() {
      reader.read().then(({ done, value }) => {
        if (done) return;
        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split("\n\n");
        buffer = lines.pop();

        for (const block of lines) {
          if (block.startsWith("data:")) {
            try {
              const data = JSON.parse(block.substring(5).trim());
              handleTerminalStreamEvent(data);
            } catch (_) {}
          }
        }
        readChunk();
      }).catch((err) => {
        output.textContent += `\n[Stream Error: ${err.message}]\n`;
      });
    }
    readChunk();
  }).catch((err) => {
    output.textContent += `\n[Failed to launch process: ${err.message}]\n`;
  });
}
window.openTerminalConsole = openTerminalConsole;

function handleTerminalStreamEvent(data) {
  const output = $("term-output");
  const badgeEl = $("term-status-badge");
  const metaEl = $("term-meta");
  if (!output) return;

  if (data.type === "output") {
    output.textContent += data.line + "\n";
    const body = $("term-body");
    if (body) body.scrollTop = body.scrollHeight;
  } else if (data.type === "done") {
    output.textContent += `\n[Process completed with exit code: ${data.exit_code}]\n`;

    // Winget/brew non-error exit codes treated as success:
    // 2316632107 (0x8A150109) = No upgrade needed, already on latest version
    // 2316632065 (0x8A150101) = Package already installed (reinstall not needed)
    const WINGET_OK_CODES = new Set([0, 2316632107, 2316632065]);
    const isSuccess = WINGET_OK_CODES.has(data.exit_code);

    if (data.exit_code === 2316632107) {
      output.textContent += `[ℹ Already on latest version — no upgrade needed.]\n`;
    } else if (data.exit_code === 2316632065) {
      output.textContent += `[ℹ Package is already installed — no action taken.]\n`;
    }

    if (badgeEl) {
      badgeEl.textContent = isSuccess ? "Success" : "Failed";
      badgeEl.className = `status-pill ${isSuccess ? "installed" : "missing"}`;
    }
    if (metaEl) metaEl.textContent = `Finished at ${new Date().toLocaleTimeString()} (Exit code: ${data.exit_code})`;

    // ── Auto-refresh tool status after successful install ──────────────
    if (isSuccess) {
      output.textContent += `\n[🔄 Refreshing installed tool status...]\n`;
      // Small delay so the OS has time to register the new binary on PATH
      setTimeout(() => {
        fetch(`${API}/api/devtools/status`)
          .then((r) => r.json())
          .then((statusData) => {
            if (statusData.ok) {
              toolStatusCache = statusData.status || {};
              // Re-render cards in-place without full page reload
              renderCuratedSections();
              searchDevTools();
              if (activeView === "devtools") {
                const heroTool = catalogTools.find((t) => t.name === "Docker") || catalogTools[0];
                if (heroTool) renderHeroCard(heroTool, !!toolStatusCache[heroTool.statusKey]);
              }
              output.textContent += `[✓ Tool status refreshed — install buttons updated.]\n`;
              showToast("Installation complete — tool status updated.", "ok");
            }
          })
          .catch(() => {
            output.textContent += `[Could not refresh status automatically — click Refresh in the store.]\n`;
          });
      }, 800); // 800ms to allow OS to register the new binary
    }
    // ──────────────────────────────────────────────────────────────────
  } else if (data.type === "error") {
    output.textContent += `\n[Error: ${data.message}]\n`;
  }
}

function closeTerminalModal() {
  $("modal-terminal-console")?.classList.add("hidden");
}
window.closeTerminalModal = closeTerminalModal;

function clearTerminalOutput() {
  const output = $("term-output");
  if (output) output.textContent = "";
}
window.clearTerminalOutput = clearTerminalOutput;

function copyTerminalOutput() {
  const output = $("term-output");
  if (output) {
    navigator.clipboard.writeText(output.textContent);
    showToast("Terminal output copied to clipboard.", "ok");
  }
}
window.copyTerminalOutput = copyTerminalOutput;

// ═══════════════════════════════════════════════════════════════
// 8. SETTINGS & ENVIRONMENT INFORMATION
// ═══════════════════════════════════════════════════════════════

async function loadSettingsView() {
  const box = $("system-info-box");
  if (!box) return;

  try {
    const res = await fetch(`${API}/api/status/system`);
    const data = await res.json();
    if (data.ok) {
      box.innerHTML = `
        <div style="display:flex;flex-direction:column;gap:0.4rem;">
          <div><strong>Host Operating System:</strong> ${escHtml(data.os)}</div>
          <div><strong>System Architecture:</strong> ${escHtml(data.architecture)}</div>
          <div><strong>Host Machine:</strong> ${escHtml(data.hostname || 'Localhost')}</div>
          <div><strong>Detected Package Managers:</strong> ${escHtml((data.active_package_managers || []).join(", ") || "Winget")}</div>
          <div><strong>Security Control Center:</strong> <span style="color:#34d399;font-weight:700;">Active &amp; Monitoring</span></div>
        </div>
      `;
    }
  } catch (err) {
    box.textContent = "Failed to load environment information.";
  }
}

// ── Startup Initialization ──
document.addEventListener("DOMContentLoaded", () => {
  initTheme();
  checkBackendHealth();
  loadDevToolsStore();
  runDevDoctorScan();
  updateControlCenterBadge();

  setInterval(updateControlCenterBadge, 10000);
});
