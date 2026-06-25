const { chromium } = require('playwright');
const { pathToFileURL } = require('url');
const path = require('path');
const fs = require('fs');

(async () => {
  const browser = await chromium.launch({ headless: true });
  const page = await browser.newPage({ viewport: { width: 1280, height: 850 } });
  const appUrl = pathToFileURL(path.join(__dirname, '..', 'frontend', 'index.html')).toString();

  // Create artifacts screenshot folder if it doesn't exist
  const artifactDir = '/home/rooster/.gemini/antigravity/brain/d9da8558-37d4-4065-8f87-afaafe5b264b/artifacts';
  if (!fs.existsSync(artifactDir)) {
    fs.mkdirSync(artifactDir, { recursive: true });
  }

  await page.addInitScript(() => {
    window.desktop = {
      getBackendStatus: async () => 'online',
      onBackendStatus: () => {},
    };
  });

  await page.route('http://127.0.0.1:8765/api/**', async route => {
    const url = route.request().url();
    const json = body => route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(body) });

    if (url.includes('/api/sysinfo')) return json({ os: 'Linux', cpu_percent: 12, ram_used_gb: 5.4, ram_total_gb: 16, disk_used_gb: 120, disk_total_gb: 512, os_label: 'Zorin OS 18.1' });
    if (url.includes('/api/dashboard/resources')) return json({ ok: true, roots: [{ label: 'Home', path: '/home/rooster' }], apps: [{ name: 'VS Code', command: 'code', category: 'Dev', cpu_percent: 2.1, memory_percent: 3.4, pids: [4321] }] });
    if (url.includes('/api/gpu_usage')) {
      return json({
        ok: true,
        available: true,
        gpus: [
          {
            name: "Intel UHD Graphics (Integrated)",
            kind: "integrated",
            kind_label: "Integrated GPU",
            available: true,
            usage_pct: 28,
            mem_used_mb: 850,
            mem_total_mb: 4096,
            temperature_c: 42,
            source: "system"
          },
          {
            name: "NVIDIA GeForce RTX 3050 Ti Laptop GPU (Dedicated)",
            kind: "dedicated",
            kind_label: "Dedicated GPU",
            available: false, // Inactive dedicated GPU (should be dissolved)
            usage_pct: 0,
            source: "nvidia-smi"
          }
        ]
      });
    }
    if (url.includes('/api/recipes')) return json({ ok: true, recipes: [] });
    if (url.includes('/api/tools_status')) return json({ ok: true, tools: { git: true, python3: true, pip: true, node: true, npm: true, docker: true, code: true, java: true, java_home: true, ollama: true } });
    if (url.includes('/api/commands/actions')) return json({ ok: true, actions: [] });
    if (url.includes('/api/logs')) return json({ ok: true, count: 0, logs: [] });
    if (url.includes('/api/self-healing/status')) {
      return json({
        ok: true,
        system_health: 98,
        adaptation_score: 90,
        attempts: [],
        analytics: { total_attempts: 4, success_count: 4, failure_count: 0, rollback_count: 0 }
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
        issues: []
      });
    }
    if (url.includes('/api/ollama/status')) {
      return json({
        running: true,
        models: ["phi3:mini"]
      });
    }
    return json({ ok: true });
  });

  try {
    await page.goto(appUrl);
    await page.waitForSelector('#sidebar');

    // 1. Dashboard Screen (centered integrated GPU ring, dissolved dedicated)
    await page.click('#nav-dashboard');
    // Wait for the rings to render
    await page.waitForTimeout(1000);
    await page.screenshot({ path: path.join(artifactDir, 'dashboard_gpu_verification.png') });
    console.log('Saved dashboard_gpu_verification.png');

    // 2. Scan Screen (verify SVG checkmarks)
    await page.click('#nav-scan');
    await page.click('#btn-scan');
    // Wait for scan to run and show checkmarks
    await page.waitForTimeout(1500);
    await page.screenshot({ path: path.join(artifactDir, 'scan_svg_verification.png') });
    console.log('Saved scan_svg_verification.png');

    // 3. AI Terminal Screen (ChatGPT style theme)
    await page.click('#nav-terminal-ai');
    await page.fill('#agent-input', 'My Python environment is giving pip errors');
    // Trigger message append manually or by clicking send
    await page.click('#agent-send-btn');
    await page.waitForTimeout(1500);
    await page.screenshot({ path: path.join(artifactDir, 'ai_terminal_chatgpt_verification.png') });
    console.log('Saved ai_terminal_chatgpt_verification.png');

    await browser.close();
    console.log('All screenshots taken successfully.');
    process.exit(0);
  } catch (err) {
    console.error('Failed to take screenshots:', err);
    await browser.close();
    process.exit(1);
  }
})();
