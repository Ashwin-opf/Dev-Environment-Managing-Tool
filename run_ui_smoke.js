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
    await page.goto(appUrl);
    await page.waitForSelector('#sidebar');

    const navs = ['dashboard', 'scan', 'repair', 'optimize', 'devtools', 'drivers', 'terminal-ai', 'logs'];
    for (const nav of navs) {
      await page.click(`#nav-${nav}`);
      const className = await page.$eval(`#view-${nav}`, el => el.className);
      if (!/active/.test(className)) throw new Error(`View ${nav} not active`);
    }

    await page.click('#nav-repair');
    await page.waitForSelector('#recipe-list .recipe-card');
    const count = await page.$$eval('#recipe-list .recipe-card', els => els.length);
    if (count !== 2) throw new Error('Expected 2 recipe cards');

    await page.click('#recipe-list .action-btn');
    await page.waitForSelector('#modal-overlay');
    const modalCmd = await page.$eval('#modal-command', el => el.textContent || el.innerText);
    if (!modalCmd.includes('sudo apt-get install -y git')) throw new Error('Modal command missing git install');
    await page.click('.btn-cancel');

    await page.fill('#repair-search', 'temp');
    const afterCount = await page.$$eval('#recipe-list .recipe-card', els => els.length);
    if (afterCount !== 1) throw new Error('Search filtering failed');

    await page.click('#nav-logs');
    await page.click('#view-logs .primary-btn');
    await page.waitForFunction(() => {
      const el = document.querySelector('#log-box');
      return el && el.textContent && !el.textContent.includes('Loading');
    }, { timeout: 5000 });
    const logsText = await page.$eval('#log-box', el => el.textContent || '');
    console.log('LOGS TEXT START\n' + logsText + '\nLOGS TEXT END');
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

    await page.click('#nav-devtools');
    await page.waitForSelector('#devtools-suggestions');
    await page.click('button:has-text("Refresh Suggestions")');
    await page.waitForFunction(() => {
      const container = document.querySelector('#devtools-suggestions');
      return container && container.querySelectorAll('.module-card').length > 0;
    }, { timeout: 5000 });
    const suggestions = await page.$$eval('#devtools-suggestions .module-card', els => els.map(el => el.textContent || ''));
    if (suggestions.length === 0) throw new Error('No devtools suggestions rendered');

    console.log('UI smoke checks passed');
    await browser.close();
    process.exit(0);
  } catch (err) {
    console.error('UI smoke failed:', err);
    await browser.close();
    process.exit(2);
  }
})();
