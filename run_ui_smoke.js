const { chromium } = require('playwright');
const { pathToFileURL } = require('url');
const path = require('path');

(async () => {
  const browser = await chromium.launch({
    headless: true,
    args: ['--allow-file-access-from-files', '--no-sandbox', '--disable-setuid-sandbox']
  });
  const page = await browser.newPage({ viewport: { width: 1280, height: 820 } });
  const appUrl = pathToFileURL(path.join(__dirname, 'frontend', 'index.html')).toString();

  await page.addInitScript(() => {
    window.desktop = {
      getBackendStatus: async () => 'offline',
      onBackendStatus: () => {},
    };
  });

  await page.route('http://127.0.0.1:8765/api/**', async route => {
    const url = route.request().url();
    const json = body => route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(body) });

    if (url.includes('/api/sysinfo')) return json({ os: 'Linux', cpu_percent: 8, ram_used_gb: 4, ram_total_gb: 16, disk_used_gb: 120, disk_total_gb: 512 });
    if (url.includes('/api/dashboard/resources')) return json({ ok: true, roots: [{ label: 'Home', path: '/home/test' }], apps: [{ name: 'Editor', command: 'code', category: 'Dev', cpu_percent: 1.2, memory_percent: 4.5, pids: [123] }] });
    if (url.includes('/api/files/list')) return json({ ok: true, path: '/home/test', parent: null, writable: true, entries: [{ type: 'file', name: 'notes.txt', path: '/home/test/notes.txt', editable: true, writable: true, size_gb: 0.001 }] });
    if (url.includes('/api/recipes')) return json({ ok: true, recipes: [ { issue: 'Git missing', command: 'sudo apt-get install -y git', explanation: 'Install Git safely from the OS package manager.', os: 'Linux', risk: 'Medium' }, { issue: 'Clear temporary files', command: 'find /tmp -mindepth 1 -user $(whoami) -delete', explanation: 'Clean user temp files.', os: 'Linux', risk: 'Low' } ] });
    if (url.includes('/api/tools_status')) return json({ ok: true, tools: { git: false, python3: true, pip: true, node: true, npm: true, docker: false, code: true, java: true, java_home: true, ollama: true } });
    if (url.includes('/api/commands/actions')) return json({ ok: true, actions: [] });
    if (url.includes('/api/logs')) return json({ logs: [ JSON.stringify({ timestamp: '2026-06-05T08:00:00Z', action: 'EXECUTE', command: 'older command', detail: 'old detail' }), JSON.stringify({ timestamp: '2026-06-05T09:00:00Z', action: 'EXECUTE', command: 'newer command', detail: 'new detail' }) ] });
    if (url.includes('/api/self-healing/status')) {
      return json({
        ok: true,
        system_health: 95,
        adaptation_score: 80,
        attempts: [],
        registry_mappings: [],
        analytics: {
          total_attempts: 10,
          success_count: 8,
          failure_count: 2,
          rollback_count: 1,
          success_rate: 0.8,
          trusted_count: 5,
          experimental_count: 3,
          degraded_count: 0
        }
      });
    }
    if (url.includes('/api/scan/steps')) {
      return json({
        ok: true,
        steps: [
          { id: 'memory', title: 'Memory Health Check' },
          { id: 'storage', title: 'Storage Health Check' }
        ]
      });
    }
    if (url.includes('/api/scan/run')) {
      return json({
        ok: true,
        issues: [{ severity: 'low', title: 'Git missing', detail: 'Git is unavailable', recipe_hint: 'Git missing' }]
      });
    }
    if (url.includes('/api/scan')) return json({ ok: true, issues: [{ severity: 'low', title: 'Git missing', detail: 'Git is unavailable', recipe_hint: 'Git missing' }] });
    if (url.includes('/api/execute')) return json({ ok: true, stdout: 'ok', stderr: '', returncode: 0 });
    if (url.includes('/api/drivers')) return json({ ok: true, gpu: 'Integrated', recommendations: [] });
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
    if (url.includes('/api/devtools/resolve')) {
      return json({
        ok: true,
        status: 'auto_selected',
        confidence: 95.0,
        from_cache: false,
        source_used: 'winget',
        install_cmd: 'winget install VideoLAN.VLC',
        selected: {
          pkg_id: 'VideoLAN.VLC',
          name: 'VLC media player',
          version: '3.0.20',
          manager: 'winget',
          source: 'winget',
          publisher: 'VideoLAN',
          homepage: 'https://www.videolan.org',
          description: 'VLC is a free and open source cross-platform multimedia player.',
          fuzzy_score: 95.0,
          trust_score: 100.0,
          total_score: 95.0,
          variant_tags: [],
          verified: true,
          install_cmd: 'winget install VideoLAN.VLC'
        },
        candidates: []
      });
    }
    if (url.includes('/api/devtools/suggest')) return json({ ok: true, suggestions: [ { app: 'Poetry', trigger_app: 'Python', category: 'Dependency Manager', description: 'Premium Python dependency manager using pyproject.toml.', icon: '🐍' }, { app: 'pnpm', trigger_app: 'Node.js', category: 'Package Manager', description: 'Faster and more efficient Node package installs.', icon: '📦' } ] });
    if (url.includes('/api/devtools/extract')) return json({ ok: true, title: 'Install Poetry', command: 'curl -sSL https://install.python-poetry.org | python3 -', purpose: 'Install Poetry from the official installer.', affects: 'Python toolchain' });
    if (url.includes('/api/ai_agent')) return json({ ok: true, response: 'Check Git:\n```bash\ngit --version\n```' });
    return json({ ok: true });
  });

  page.on('pageerror', exception => {
    console.log(`Browser Uncaught exception: "${exception}"`);
  });
  page.on('console', msg => {
    console.log(`Browser console: ${msg.text()}`);
  });

  try {
    console.log('Navigating to appUrl:', appUrl);
    await page.goto(appUrl);
    await page.waitForSelector('#sidebar');
    console.log('Sidebar loaded');

    const navs = ['dashboard', 'scan', 'optimize', 'devtools', 'myapps', 'drivers', 'terminal-ai', 'logs', 'control-center'];
    for (const nav of navs) {
      console.log('Clicking nav:', nav);
      await page.click(`#nav-${nav}`);
      await page.waitForSelector(`#view-${nav === 'control-center' ? 'control-center' : nav}.active`, { timeout: 3000 });
    }
    console.log('All views activated successfully');

    // Verify My Apps View
    console.log('Testing My Apps view assertions...');
    await page.click('#nav-myapps');
    await page.waitForSelector('#myapps-grid .store-tool-card.myapp-card', { timeout: 4000 });
    const myAppTitle = await page.$eval('#myapps-grid .tool-card-name', el => el.textContent.trim());
    console.log('My Apps found card:', myAppTitle);
    if (myAppTitle !== 'Git') throw new Error(`Expected Git in My Apps, got ${myAppTitle}`);
    const statTotal = await page.$eval('#myapps-stat-total', el => el.textContent.trim());
    if (statTotal !== '1') throw new Error(`Expected total 1, got ${statTotal}`);

    // Test search filter in My Apps
    console.log('Testing search filter in My Apps...');
    await page.fill('#myapps-search-input', 'Git');
    const visibleCount = await page.$$eval('#myapps-grid .store-tool-card.myapp-card', els => els.filter(e => e.style.display !== 'none').length);
    if (visibleCount !== 1) throw new Error('Search filtering for Git failed');
    await page.fill('#myapps-search-input', 'NonExistentApp123');
    const emptyVisible = await page.$eval('#myapps-empty', el => !el.classList.contains('hidden'));
    if (!emptyVisible) throw new Error('Empty state should show for non-existent app');
    await page.fill('#myapps-search-input', '');
    console.log('My Apps checks passed!');

    await page.click('#nav-logs');
    await page.waitForFunction(() => {
      const el = document.querySelector('#log-list');
      return el && el.textContent && !el.textContent.includes('Loading');
    }, { timeout: 5000 });
    const logsText = await page.$eval('#log-list', el => el.textContent || '');
    console.log('LOGS TEXT:', logsText);
    if (!logsText.includes('newer command')) throw new Error('Logs missing newer command');

    await page.click('#nav-terminal-ai');
    await page.click('#ollama-toggle-btn');
    await page.waitForSelector('#ollama-panel');
    const panelHtml = await page.$eval('#ollama-panel', el => el.innerHTML || '');
    console.log('OLLAMA PANEL HTML START\n' + panelHtml + '\nOLLAMA PANEL HTML END');
    await page.waitForSelector('.ollama-quick-btn');
    const ollamaButtons = await page.$$eval('.ollama-quick-btn', els => els.map(e => e.textContent || ''));
    const target = ollamaButtons.find(t => t && t.includes('Pull phi3:mini')) || '';
    if (!target.includes('2.2') && !target.includes('~2.2')) throw new Error('Ollama quick btn size missing');

    // Test DevTools Store & Live Search for new apps
    await page.click('#nav-devtools');
    await page.waitForSelector('.store-tool-card', { timeout: 5000 });
    const storeCards = await page.$$eval('.store-tool-card', els => els.length);
    console.log('DevTools Store rendered tool cards count:', storeCards);
    if (storeCards === 0) throw new Error('No devtools store cards rendered');

    console.log('Testing live new app search in DevTools Store (vlc)...');
    await page.fill('#devtools-search', 'vlc');
    await page.waitForSelector('#pkg-search-panel', { timeout: 4000 });
    await page.waitForSelector('#pkg-search-results div', { timeout: 6000 });
    const foundPkg = await page.$eval('#pkg-search-results', el => el.textContent);
    console.log('Live package search result:', foundPkg);
    if (!foundPkg.includes('VLC media player')) throw new Error('Expected VLC in live package search results');
    await page.fill('#devtools-search', '');

    console.log('UI smoke checks passed');
    await browser.close();
    process.exit(0);
  } catch (err) {
    console.error('UI smoke failed:', err);
    await browser.close();
    process.exit(2);
  }
})();
