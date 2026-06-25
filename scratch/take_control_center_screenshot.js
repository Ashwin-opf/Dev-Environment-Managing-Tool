const { chromium } = require('playwright');
const { pathToFileURL } = require('url');
const path = require('path');
const fs = require('fs');

(async () => {
  const browser = await chromium.launch({ headless: true });
  const page = await browser.newPage({ viewport: { width: 1280, height: 850 } });
  const appUrl = pathToFileURL(path.join(__dirname, '..', 'frontend', 'index.html')).toString();

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
    if (url.includes('/api/dashboard/resources')) return json({ ok: true, roots: [{ label: 'Home', path: '/home/rooster' }], apps: [] });
    if (url.includes('/api/gpu_usage')) return json({ ok: true, available: true, gpus: [] });
    if (url.includes('/api/recipes')) return json({ ok: true, recipes: [] });
    if (url.includes('/api/tools_status')) return json({ ok: true, tools: {} });
    if (url.includes('/api/commands/actions')) return json({ ok: true, actions: [] });
    if (url.includes('/api/logs')) return json({ ok: true, count: 0, logs: [] });
    if (url.includes('/api/shce/dashboard')) {
      return json({
        ok: true,
        status: {
          core_active: true,
          safety_ok: true,
          auto_repairs_session: 12,
          success_rate: 100,
          queue_depth: 0,
        },
        knowledge_base: { total: 45 },
        progress: { overall: 85, repair: 90, optimize: 80, devtools: 85, package_commands: 85 }
      });
    }
    if (url.includes('/api/adaptation/status')) {
      return json({
        ok: true,
        profile: { os_label: 'Zorin OS 18.1', kernel: '6.5.0-35-generic', architecture: 'x86_64', package_manager: 'apt' },
        progress: { overall: 85, repair: 90, optimize: 80, devtools: 85, package_commands: 85 }
      });
    }
    return json({ ok: true });
  });

  try {
    await page.goto(appUrl);
    await page.waitForSelector('#sidebar');

    // Hover over the sidebar footer bar to trigger hover styles
    await page.hover('#os-oval-bar');
    await page.waitForTimeout(500);

    // Click to navigate to Control Center
    await page.click('#os-oval-bar');
    await page.waitForTimeout(1000);

    // Take screenshot of the Control Center view
    const screenshotPath = path.join(artifactDir, 'control_center_verification.png');
    await page.screenshot({ path: screenshotPath });
    console.log(`Saved screenshot to ${screenshotPath}`);

    await browser.close();
    process.exit(0);
  } catch (err) {
    console.error('Failed to take screenshot:', err);
    await browser.close();
    process.exit(1);
  }
})();
