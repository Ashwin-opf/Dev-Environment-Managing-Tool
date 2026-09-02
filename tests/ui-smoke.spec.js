const { test, expect } = require('@playwright/test');
const { chromium } = require('playwright');
const { pathToFileURL } = require('url');
const path = require('path');

test('core UI controls render and respond without real system execution', async () => {
  const launchOptions = {
    headless: true,
    args: [
      '--allow-file-access-from-files',
      '--no-sandbox',
      '--disable-setuid-sandbox',
      '--disable-seccomp-filter-sandbox',
      '--disable-gpu-sandbox',
      '--disable-crash-reporter',
      '--disable-breakpad',
    ],
  };
  if (process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE) {
    launchOptions.executablePath = process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE;
  }

  const browser = await chromium.launch(launchOptions);
  const page = await browser.newPage({ viewport: { width: 1280, height: 820 } });
  const appUrl = pathToFileURL(path.join(process.cwd(), 'frontend', 'index.html')).toString();

  await page.addInitScript(() => {
    window.electron = {
      ipcRenderer: {
        invoke: async () => 'offline',
        on: () => {},
        removeAllListeners: () => {},
      },
    };
  });

  await page.route('http://127.0.0.1:8765/api/**', async route => {
    const url = route.request().url();
    const json = body => route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(body),
    });

    if (url.includes('/api/sysinfo')) {
      return json({ os: 'Linux', cpu_percent: 8, ram_used_gb: 4, ram_total_gb: 16, disk_used_gb: 120, disk_total_gb: 512 });
    }
    if (url.includes('/api/dashboard/resources')) {
      return json({
        ok: true,
        roots: [{ label: 'Home', path: '/home/test' }],
        apps: [{ name: 'Editor', command: 'code', category: 'Dev', cpu_percent: 1.2, memory_percent: 4.5, pids: [123] }],
      });
    }
    if (url.includes('/api/files/list')) {
      return json({ ok: true, path: '/home/test', parent: null, writable: true, entries: [{ type: 'file', name: 'notes.txt', path: '/home/test/notes.txt', editable: true, writable: true, size_gb: 0.001 }] });
    }
    if (url.includes('/api/recipes')) {
      return json({ ok: true, recipes: [
        { issue: 'Git missing', command: 'sudo apt-get install -y git', explanation: 'Install Git safely from the OS package manager.', os: 'Linux', risk: 'Medium' },
        { issue: 'Clear temporary files', command: 'find /tmp -mindepth 1 -user $(whoami) -delete', explanation: 'Clean user temp files.', os: 'Linux', risk: 'Low' },
      ] });
    }
    if (url.includes('/api/tools_status')) {
      return json({ ok: true, tools: { git: false, python3: true, pip: true, node: true, npm: true, docker: false, code: true, java: true, java_home: true, ollama: true } });
    }
    if (url.includes('/api/commands/actions')) {
      return json({ ok: true, actions: [] });
    }
    if (url.includes('/api/devtools/managed')) {
      return json({
        ok: true,
        apps: [
          {
            app_id: 'git',
            name: 'Git',
            category: 'Developer Tools',
            description: 'Fast, scalable, distributed revision control system.',
            package_manager: 'apt',
            installed_at: '2026-06-10T10:00:00Z',
            update_command: 'sudo apt-get update && sudo apt-get install --only-upgrade -y git',
            uninstall_command: 'sudo apt-get remove -y git'
          }
        ]
      });
    }
    if (url.includes('/api/devtools/uninstall')) {
      return json({ ok: true, app_id: 'git', name: 'Git', returncode: 0, stdout: 'Removed', stderr: '' });
    }
    if (url.includes('/api/devtools/extract')) {
      const postData = route.request().postData();
      const body = postData ? JSON.parse(postData) : {};
      const app = body.app || '';
      const gui = body.gui || false;
      return json({
        ok: true,
        title: `Install ${app}`,
        command: gui ? `sudo apt-get install -y ${app}-gui` : `sudo apt-get install -y ${app}-cli`,
        purpose: `Installs ${app}.`,
        risk: 'Medium',
        affects: app
      });
    }
    if (url.includes('/api/logs')) {
      return json({ logs: [
        JSON.stringify({ timestamp: '2026-06-05T09:00:00Z', action: 'EXECUTE', command: 'newer command', detail: 'new detail' }),
        JSON.stringify({ timestamp: '2026-06-05T08:00:00Z', action: 'EXECUTE', command: 'older command', detail: 'old detail' }),
      ] });
    }
    if (url.includes('/api/scan')) {
      return json({ ok: true, issues: [{ severity: 'low', title: 'Git missing', detail: 'Git is unavailable', recipe_hint: 'Git missing' }] });
    }
    if (url.includes('/api/execute')) {
      return json({ ok: true, stdout: 'ok', stderr: '', returncode: 0 });
    }
    if (url.includes('/api/drivers')) {
      return json({
        ok: true,
        gpus: ['Intel UHD Graphics'],
        recommended_drivers: [],
        all_drivers: [
          { device: 'Intel Corporation UHD Graphics', driver: 'i915', modules: ['i915'] }
        ],
        driver_package_updates: { available: false, checked: true, summary: 'Driver packages are up to date.', command: '' },
      });
    }
    if (url.includes('/api/gpu_usage')) {
      return json({
        ok: true,
        available: true,
        gpus: [
          { name: 'Intel UHD Graphics', kind: 'integrated', kind_label: 'Integrated GPU', available: true, usage_pct: 12, source: 'i915 sysfs' },
          { name: 'NVIDIA GeForce RTX 3050 Ti', kind: 'dedicated', kind_label: 'Dedicated GPU', available: true, usage_pct: 0, message: 'Dedicated GPU detected, but the NVIDIA driver is not loaded.' },
        ],
      });
    }
    if (url.includes('/api/ai_agent')) {
      return json({ ok: true, response: 'Check Git:\n```bash\ngit --version\n```' });
    }
    // ── SHCE Control Center mock routes ──
    if (url.includes('/api/shce/dashboard')) {
      return json({
        ok: true,
        status: { core_active: true, safety_ok: true, ollama_running: false, network_online: true, auto_repairs_session: 3, success_rate: 75.0, queue_depth: 1 },
        queue: [{ id: 1, timestamp: '2026-06-13T03:00:00Z', command: 'apt install nginx', error: 'Package not found', status: 'pending', candidates: JSON.stringify([{ command: 'sudo apt-get install -f -y', source: 'Debian APT Docs', score: 7.0, safety_class: 'Caution', validation: 'Passed' }]), selected_candidate: 'sudo apt-get install -f -y', outcome_stdout: '', outcome_stderr: '', outcome_rc: null }],
        error_log: [],
        environment: { os_name: 'Linux', os_label: 'Ubuntu 24.04', kernel: '6.8.0', architecture: 'x86_64', package_manager: 'apt', distro: 'debian', network_online: true, ollama_running: false, gpu_info: 'Intel UHD', memory_gb: 16, disk_free_gb: 120, cpu_count: 8, hostname: 'testbox', python_version: '3.12.0', timestamp: '2026-06-13T03:00:00Z' },
        knowledge_base: { total: 5, trusted: 2, experimental: 2, degraded: 1, entries: [] },
      });
    }
    if (url.includes('/api/shce/status')) {
      return json({ ok: true, status: { core_active: true, safety_ok: true, auto_repairs_session: 3, success_rate: 75.0, queue_depth: 1 }, environment: { os_label: 'Ubuntu 24.04', package_manager: 'apt', network_online: true, ollama_running: false } });
    }
    if (url.includes('/api/shce/environment')) {
      return json({ ok: true, environment: { os_name: 'Linux', os_label: 'Ubuntu 24.04', kernel: '6.8.0', architecture: 'x86_64', package_manager: 'apt', distro: 'debian', network_online: true, ollama_running: false, gpu_info: 'Intel UHD', memory_gb: 16, disk_free_gb: 120, cpu_count: 8, hostname: 'testbox', python_version: '3.12.0', timestamp: '2026-06-13T03:00:00Z' } });
    }
    if (url.includes('/api/shce/error-log')) {
      return json({ ok: true, entries: [], total: 0 });
    }
    if (url.includes('/api/shce/knowledge')) {
      return json({ ok: true, total: 5, trusted: 2, experimental: 2, degraded: 1, entries: [] });
    }
    if (url.includes('/api/shce/queue')) {
      return json({ ok: true, queue: [] });
    }
    if (url.includes('/api/shce/mutate')) {
      return json({ ok: true, candidates: [{ command: 'sudo apt-get install -f -y', source: 'Debian APT Docs', score: 7.0, safety_class: 'Caution', validation: 'Passed' }], count: 1 });
    }
    if (url.includes('/api/shce/')) {
      return json({ ok: true });
    }

    return json({ ok: true });
  });

  await page.goto(appUrl);
  await page.waitForLoadState('domcontentloaded');
  await page.waitForSelector('#sidebar');

  for (const nav of ['dashboard', 'scan', 'optimize', 'devtools', 'myapps', 'drivers', 'terminal-ai', 'logs']) {
    await page.click(`#nav-${nav}`);
    await expect(page.locator(`#view-${nav}`)).toHaveClass(/active/);
  }

  await page.click('#nav-drivers');
  await expect(page.locator('#gpu-usage-card .gpu-usage-grid')).toBeVisible();
  await expect(page.locator('#gpu-usage-card .gpu-usage-item')).toHaveCount(2);
  await expect(page.locator('#drivers-results .driver-card').first()).toBeVisible();

  await page.click('#nav-logs');
  await page.click('#view-logs .primary-btn');
  await expect(page.locator('#log-box')).toContainText('newer command');
  const logsText = await page.locator('#log-box').textContent();
  expect(logsText.indexOf('newer command')).toBeLessThan(logsText.indexOf('older command'));

  await page.click('#nav-terminal-ai');
  await page.click('#ollama-toggle-btn');
  await expect(page.locator('.ollama-quick-btn:has-text("Pull phi3:mini")')).toContainText('~2.2 GB');

  await browser.close();
});

// ── SHCE Control Center dedicated smoke test ──────────────────────────────────
test('SHCE Control Center renders 6-tab panel and responds to tab navigation', async () => {
  const launchOptions = {
    args: [
      '--no-sandbox', '--disable-setuid-sandbox', '--disable-seccomp-filter-sandbox',
      '--disable-gpu-sandbox', '--disable-crash-reporter', '--disable-breakpad',
    ],
  };
  if (process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE) {
    launchOptions.executablePath = process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE;
  }

  const browser = await chromium.launch(launchOptions);
  const page = await browser.newPage({ viewport: { width: 1280, height: 820 } });
  page.on('console', msg => console.log('BROWSER LOG:', msg.text()));
  page.on('pageerror', err => console.log('BROWSER ERROR:', err.stack || err.message));

  const appUrl = pathToFileURL(path.join(process.cwd(), 'frontend', 'index.html')).toString();

  await page.addInitScript(() => {
    window.electron = {
      ipcRenderer: { invoke: async () => 'offline', on: () => {}, removeAllListeners: () => {} },
    };
  });

  await page.route('http://127.0.0.1:8765/api/**', async route => {
    const url = route.request().url();
    const json = body => route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(body) });

    if (url.includes('/api/sysinfo')) return json({ os: 'Linux', cpu_percent: 8, ram_used_gb: 4, ram_total_gb: 16, disk_used_gb: 120, disk_total_gb: 512 });
    if (url.includes('/api/dashboard/resources')) return json({ ok: true, roots: [], apps: [] });
    if (url.includes('/api/shce/dashboard')) return json({
      ok: true,
      status: { core_active: true, safety_ok: true, ollama_running: false, network_online: true, auto_repairs_session: 3, success_rate: 75.0, queue_depth: 1 },
      queue: [],
      error_log: [],
      environment: { os_name: 'Linux', os_label: 'Ubuntu 24.04', kernel: '6.8.0', architecture: 'x86_64', package_manager: 'apt', distro: 'debian', network_online: true, ollama_running: false, gpu_info: 'Intel UHD', memory_gb: 16, disk_free_gb: 120, cpu_count: 8, hostname: 'testbox', python_version: '3.12.0', timestamp: '2026-06-13T03:00:00Z' },
      knowledge_base: { total: 5, trusted: 2, experimental: 2, degraded: 1, entries: [] },
    });
    if (url.includes('/api/shce/environment')) return json({ ok: true, environment: { os_name: 'Linux', os_label: 'Ubuntu 24.04', kernel: '6.8.0', architecture: 'x86_64', package_manager: 'apt', distro: 'debian', network_online: true, ollama_running: false, gpu_info: 'Intel UHD', memory_gb: 16, disk_free_gb: 120, cpu_count: 8, hostname: 'testbox', python_version: '3.12.0', timestamp: '2026-06-13T03:00:00Z' } });
    if (url.includes('/api/shce/error-log')) return json({ ok: true, entries: [], total: 0 });
    if (url.includes('/api/shce/knowledge')) return json({ ok: true, total: 5, trusted: 2, experimental: 2, degraded: 1, entries: [] });
    if (url.includes('/api/shce/queue')) return json({ ok: true, queue: [] });
    if (url.includes('/api/shce/')) return json({ ok: true });
    if (url.includes('/api/adaptation')) return json({ ok: true, os: 'Linux', adaptations: [], progress: { total: 0, adapted: 0 } });
    return json({ ok: true });
  });

  await page.goto(appUrl);
  await page.waitForLoadState('domcontentloaded');
  await page.waitForSelector('#sidebar');

  // Navigate to SHCE view via the OS pill button
  await page.evaluate(() => window.openOsAdaptationTab && window.openOsAdaptationTab());
  await expect(page.locator('#view-os-adaptation')).toBeVisible();

  // Stat tiles should be visible
  await expect(page.locator('.shce-tiles-row')).toBeVisible();
  await expect(page.locator('#shce-core-status')).toBeVisible();
  await expect(page.locator('#shce-safety-status')).toBeVisible();
  await expect(page.locator('#shce-repairs-count')).toBeVisible();
  await expect(page.locator('#shce-success-rate')).toBeVisible();
  await expect(page.locator('#shce-queue-depth')).toBeVisible();
  await expect(page.locator('#shce-kb-size')).toBeVisible();

  // Tab bar: 6 tabs
  await expect(page.locator('#view-os-adaptation .shce-tab-bar')).toBeVisible();
  await expect(page.locator('#view-os-adaptation .shce-tab')).toHaveCount(6);

  // Overview tab is active by default
  await expect(page.locator('#shce-section-overview')).toHaveClass(/active/);

  // Switch to Queue tab
  await page.evaluate(() => window.switchSHCETab('queue'));
  await expect(page.locator('#shce-section-queue')).toHaveClass(/active/);
  await expect(page.locator('#shce-queue-list')).toBeVisible();

  // Switch to Error Monitor tab
  await page.evaluate(() => window.switchSHCETab('errors'));
  await expect(page.locator('#shce-section-errors')).toHaveClass(/active/);
  await expect(page.locator('#shce-error-log')).toBeVisible();

  // Switch to Knowledge Base tab
  await page.evaluate(() => window.switchSHCETab('knowledge'));
  await expect(page.locator('#shce-section-knowledge')).toHaveClass(/active/);
  await expect(page.locator('#shce-kb-search')).toBeVisible();
  await expect(page.locator('#shce-kb-table')).toBeVisible();

  // Switch to History tab
  await page.evaluate(() => window.switchSHCETab('history'));
  await expect(page.locator('#shce-section-history')).toHaveClass(/active/);

  // Switch to Environment tab
  await page.evaluate(() => window.switchSHCETab('environment'));
  await expect(page.locator('#shce-section-environment')).toHaveClass(/active/);
  await expect(page.locator('#shce-env-grid')).toBeVisible();

  // Return to Overview
  await page.evaluate(() => window.switchSHCETab('overview'));
  await expect(page.locator('#shce-section-overview')).toHaveClass(/active/);

  await browser.close();
});

test('DevTools dynamic search installer renders search-to-install card with slider round toggle', async () => {
  const launchOptions = {
    args: [
      '--no-sandbox', '--disable-setuid-sandbox', '--disable-seccomp-filter-sandbox',
      '--disable-gpu-sandbox', '--disable-crash-reporter', '--disable-breakpad',
    ],
  };
  if (process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE) {
    launchOptions.executablePath = process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE;
  }

  const browser = await chromium.launch(launchOptions);
  const page = await browser.newPage({ viewport: { width: 1280, height: 820 } });
  
  const appUrl = pathToFileURL(path.join(process.cwd(), 'frontend', 'index.html')).toString();

  await page.addInitScript(() => {
    window.electron = {
      ipcRenderer: { invoke: async () => 'offline', on: () => {}, removeAllListeners: () => {} },
    };
  });

  await page.route('http://127.0.0.1:8765/api/**', async route => {
    const url = route.request().url();
    const json = body => route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(body) });

    if (url.includes('/api/sysinfo')) return json({ os: 'Linux', cpu_percent: 8, ram_used_gb: 4, ram_total_gb: 16, disk_used_gb: 120, disk_total_gb: 512 });
    if (url.includes('/api/dashboard/resources')) return json({ ok: true, roots: [], apps: [] });
    if (url.includes('/api/tools_status')) {
      return json({ ok: true, tools: { git: true, python3: true } });
    }
    if (url.includes('/api/devtools/extract')) {
      const postData = route.request().postData();
      const body = postData ? JSON.parse(postData) : {};
      const app = body.app || '';
      const gui = body.gui || false;
      return json({
        ok: true,
        title: `Install ${app}`,
        command: gui ? `sudo apt-get install -y ${app}-gui` : `sudo apt-get install -y ${app}-cli`,
        purpose: `Installs ${app}.`,
        risk: 'Medium',
        affects: app
      });
    }
    if (url.includes('/api/devtools/search-packages')) {
      return json({
        ok: true,
        query: 'mysql',
        count: 1,
        results: [{
          id: 'mysql-server',
          name: 'MySQL Server',
          version: '8.0',
          source: 'apt',
          manager: 'apt',
          description: 'MySQL database server',
          publisher: 'Oracle',
          match_score: 95
        }]
      });
    }
    if (url.includes('/api/devtools/suggest')) return json({ ok: true, suggestions: [] });
    return json({ ok: true });
  });

  await page.goto(appUrl);
  await page.waitForLoadState('domcontentloaded');
  await page.waitForSelector('#sidebar');

  // Go to DevTools tab
  await page.click('#nav-devtools');
  await expect(page.locator('#view-devtools')).toHaveClass(/active/);

  // Type in the search box
  await page.fill('#devtools-search', 'mysql');
  
  // Wait for the dynamic search card to appear
  const dynamicCard = page.locator('#devtools-dynamic-search-card');
  await expect(dynamicCard).toBeVisible();

  // Verify elements inside the dynamic search card
  await expect(dynamicCard.locator('#dynamic-card-title')).toContainText('Mysql');
  await expect(dynamicCard.locator('.switch')).toBeVisible();
  await expect(dynamicCard.locator('#dynamic-command-view')).toBeVisible();
  await expect(dynamicCard.locator('#dynamic-install-btn')).toBeVisible();

  // Check the initial CLI command value in textarea
  await page.waitForFunction(() => {
    const textarea = document.getElementById('dynamic-command-view');
    return textarea && textarea.value.includes('mysql-cli');
  });

  // Toggle GUI switch
  await page.click('.switch span.slider');

  // Check the updated GUI command value in textarea
  await page.waitForFunction(() => {
    const textarea = document.getElementById('dynamic-command-view');
    return textarea && textarea.value.includes('mysql-gui');
  });

  // Click Run/Fix button
  await page.click('#dynamic-install-btn');
  await expect(page.locator('#modal-overlay')).toBeVisible();
  await expect(page.locator('#modal-command')).toContainText('sudo apt-get install -y mysql-gui');

  // Close modal
  await page.click('.btn-cancel');
  await expect(page.locator('#modal-overlay')).not.toBeVisible();

  await browser.close();
});

// ── My Apps (Installed Apps & Real-time Updates) dedicated test ─────────────
test('My Apps view renders installed apps and triggers real-time update and uninstall controls', async () => {
  const launchOptions = {
    headless: true,
    args: [
      '--allow-file-access-from-files',
      '--no-sandbox', '--disable-setuid-sandbox', '--disable-seccomp-filter-sandbox',
      '--disable-gpu-sandbox', '--disable-crash-reporter', '--disable-breakpad',
    ],
  };
  if (process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE) {
    launchOptions.executablePath = process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE;
  }

  const browser = await chromium.launch(launchOptions);
  const page = await browser.newPage({ viewport: { width: 1280, height: 820 } });
  const appUrl = pathToFileURL(path.join(process.cwd(), 'frontend', 'index.html')).toString();

  await page.addInitScript(() => {
    window.electron = {
      ipcRenderer: { invoke: async () => 'offline', on: () => {}, removeAllListeners: () => {} },
    };
  });

  await page.route('http://127.0.0.1:8765/api/**', async route => {
    const url = route.request().url();
    const json = body => route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(body) });

    if (url.includes('/api/sysinfo')) return json({ os: 'Linux', cpu_percent: 8, ram_used_gb: 4, ram_total_gb: 16, disk_used_gb: 120, disk_total_gb: 512 });
    if (url.includes('/api/dashboard/resources')) return json({ ok: true, roots: [], apps: [] });
    if (url.includes('/api/devtools/managed')) {
      return json({
        ok: true,
        apps: [
          {
            app_id: 'git',
            name: 'Git',
            category: 'Developer Tools',
            description: 'Fast, scalable, distributed revision control system.',
            package_manager: 'apt',
            installed_at: '2026-06-10T10:00:00Z',
            update_command: 'sudo apt-get update && sudo apt-get install --only-upgrade -y git',
            uninstall_command: 'sudo apt-get remove -y git'
          }
        ]
      });
    }
    if (url.includes('/api/devtools/uninstall')) {
      return json({ ok: true, app_id: 'git', name: 'Git', returncode: 0, stdout: 'Removed', stderr: '' });
    }
    return json({ ok: true });
  });

  await page.goto(appUrl);
  await page.waitForLoadState('domcontentloaded');
  await page.waitForSelector('#sidebar');

  // Navigate to My Apps
  await page.click('#nav-myapps');
  await expect(page.locator('#view-myapps')).toHaveClass(/active/);
  await expect(page.locator('#view-title')).toHaveText('My Apps');

  // Verify stat summary tiles
  await expect(page.locator('#myapps-stat-total')).toHaveText('1');
  await expect(page.locator('#myapps-stat-up-to-date')).toHaveText('All Ready');

  // Verify app card renders with unified tool-card structure
  const myAppCard = page.locator('#myapp-card-git');
  await expect(myAppCard).toBeVisible();
  await expect(myAppCard.locator('.tool-card-name')).toHaveText('Git');
  await expect(myAppCard.locator('#myapp-badge-git')).toContainText('Installed');
  await expect(myAppCard.locator('#myapp-updbtn-git')).toBeVisible();
  await expect(myAppCard.locator('#myapp-uninbtn-git')).toBeVisible();

  // Test search filtering in My Apps
  await page.fill('#myapps-search-input', 'Git');
  await expect(myAppCard).toBeVisible();
  await page.fill('#myapps-search-input', 'NonExistentApp123');
  await expect(myAppCard).not.toBeVisible();
  await page.fill('#myapps-search-input', '');
  await expect(myAppCard).toBeVisible();

  await browser.close();
});



