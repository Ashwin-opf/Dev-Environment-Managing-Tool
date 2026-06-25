const { _electron: electron } = require('playwright');
const fs = require('fs');
const path = require('path');
const { execSync } = require('child_process');

const ARTIFACT_DIR = '/home/rooster/.gemini/antigravity/brain/b80538a0-5af6-43e5-9b00-91f969d40b43';
const SCREENSHOT_DIR = path.join(ARTIFACT_DIR, 'screenshots');

// Ensure directories exist
fs.mkdirSync(SCREENSHOT_DIR, { recursive: true });

(async () => {
  console.log('[Validation] Starting Deep Feature Validation...');

  // Track logs, errors, and responses
  const consoleLogs = [];
  const pageErrors = [];
  const networkRequests = [];
  const networkResponses = [];

  const app = await electron.launch({
    args: ['.'],
    cwd: process.cwd()
  });

  const window = await app.firstWindow();
  await window.waitForLoadState('domcontentloaded');

  // Register listeners
  window.on('console', msg => {
    const text = msg.text();
    consoleLogs.push({ type: msg.type(), text });
    console.log(`[Browser Console] [${msg.type()}] ${text}`);
  });

  window.on('pageerror', err => {
    const stack = err.stack || err.message;
    pageErrors.push(stack);
    console.error(`[Browser PageError] ${stack}`);
  });

  window.on('request', req => {
    if (req.url().includes('/api/')) {
      networkRequests.push({
        url: req.url(),
        method: req.method(),
        postData: req.postData() || ''
      });
    }
  });

  window.on('response', async res => {
    if (res.url().includes('/api/')) {
      let bodyJson = null;
      let bodyText = '';
      try {
        bodyJson = await res.json();
      } catch {
        try {
          bodyText = await res.text();
        } catch (_) {}
      }
      networkResponses.push({
        url: res.url(),
        status: res.status(),
        bodyJson,
        bodyText
      });
    }
  });

  // Helper function to capture screenshot
  async function capture(name) {
    const filePath = path.join(SCREENSHOT_DIR, name);
    await window.screenshot({ path: filePath });
    console.log(`[Validation] Captured screenshot: ${name}`);
  }

  // 1. Wait for backend to be online
  console.log('[Validation] Waiting for backend to bind and come online...');
  await window.waitForFunction(() => {
    const status = document.getElementById('status-label')?.textContent;
    return status && status.includes('online');
  }, null, { timeout: 15000 });

  // 2. Dashboard View & Hardware Scanner & System Info
  console.log('[Validation] Checking Dashboard & Hardware Scanner...');
  await window.click('#nav-dashboard');
  await window.waitForTimeout(2000); // Wait for resource fetch and graphs to load
  await capture('1_dashboard.png');

  const cpuText = await window.$eval('#cpu-ring-val', el => el.textContent.trim());
  const ramText = await window.$eval('#ram-ring-val', el => el.textContent.trim());
  const diskText = await window.$eval('#disk-ring-val', el => el.textContent.trim());
  console.log(`[Validation] Hardware metrics - CPU: ${cpuText}, RAM: ${ramText}, Disk: ${diskText}`);

  // 3. OS Adaptation View (System Info)
  console.log('[Validation] Checking OS Adaptation view...');
  await window.evaluate(() => openOsAdaptationTab());
  await window.waitForSelector('#view-os-adaptation');
  await window.waitForTimeout(1000);
  await capture('2_os_adaptation.png');

  const sysInfoHtml = await window.$eval('#adaptation-system-info', el => el.innerHTML);
  console.log(`[Validation] System Info details:\n${sysInfoHtml}`);

  // 4. Scan View
  console.log('[Validation] Checking System Scanner view...');
  await window.click('#nav-scan');
  await window.waitForSelector('#view-scan');
  
  // Start Sequential Scan
  await window.click('#btn-scan');
  console.log('[Validation] Sequential Scan started, waiting for completion...');
  await window.waitForFunction(() => {
    const status = document.getElementById('scan-progress-status')?.textContent;
    return status && status.includes('Scan complete');
  }, null, { timeout: 20000 });
  await window.waitForTimeout(1000);
  await capture('3_scan.png');

  const scanResultsHtml = await window.$eval('#scan-results', el => el.innerHTML);
  console.log(`[Validation] Scan results container populated.`);

  // 5. Repair View
  console.log('[Validation] Checking Repair View...');
  await window.click('#nav-repair');
  await window.waitForSelector('#view-repair');
  await window.waitForTimeout(1000);
  await capture('4_repair.png');

  const recipeCardsCount = await window.$$eval('#recipe-list .recipe-card', els => els.length);
  console.log(`[Validation] Repair view loaded ${recipeCardsCount} recipe cards.`);

  // 6. Optimize View
  console.log('[Validation] Checking Optimize View...');
  await window.click('#nav-optimize');
  await window.waitForSelector('#view-optimize');
  await window.waitForTimeout(1000);
  await capture('5_optimize.png');

  const coherenceText = await window.$eval('#adaptation-ring-val', el => el.textContent.trim());
  console.log(`[Validation] Coherence progress score: ${coherenceText}`);

  // 7. DevTools View
  console.log('[Validation] Checking DevTools View...');
  await window.click('#nav-devtools');
  await window.waitForSelector('#view-devtools');
  await window.waitForTimeout(1000);
  await capture('6_devtools.png');

  // 8. Drivers View
  console.log('[Validation] Checking Drivers View...');
  await window.click('#nav-drivers');
  await window.waitForSelector('#view-drivers');
  await window.click('#btn-drivers');
  console.log('[Validation] Scanning drivers, waiting for list...');
  await window.waitForSelector('#drivers-results .driver-card', { timeout: 30000 });
  await capture('7_drivers.png');

  // 9. AI Terminal View
  console.log('[Validation] Checking AI Terminal View...');
  await window.click('#nav-terminal-ai');
  await window.waitForSelector('#view-terminal-ai');
  await window.waitForTimeout(1000);
  await capture('8_terminal_ai.png');

  // 10. Logs View
  console.log('[Validation] Checking Logs View...');
  await window.click('#nav-logs');
  await window.waitForSelector('#view-logs');
  await window.click('#view-logs button.primary-btn');
  await window.waitForTimeout(1000);
  await capture('9_logs.png');

  const logBoxText = await window.$eval('#log-box', el => el.textContent.trim());
  console.log(`[Validation] Log box content length: ${logBoxText.length}`);

  // SQLite Database checks
  console.log('[Validation] Verifying database records...');
  let dbResult = '';
  try {
    dbResult = execSync('backend/.venv/bin/python -c "' +
      'import sqlite3, json\n' +
      'conn = sqlite3.connect(\'backend/knowledge.db\')\n' +
      'cur = conn.cursor()\n' +
      'res = {}\n' +
      'try:\n' +
      '  cur.execute(\'SELECT COUNT(*) FROM self_healing_attempts\')\n' +
      '  res[\'healing_attempts\'] = cur.fetchone()[0]\n' +
      'except Exception as e: res[\'healing_attempts\'] = str(e)\n' +
      'try:\n' +
      '  cur.execute(\'SELECT COUNT(*) FROM learned_command_mappings\')\n' +
      '  res[\'learned_mappings\'] = cur.fetchone()[0]\n' +
      'except Exception as e: res[\'learned_mappings\'] = str(e)\n' +
      'try:\n' +
      '  cur.execute(\'SELECT COUNT(*) FROM safety_overrides\')\n' +
      '  res[\'safety_overrides\'] = cur.fetchone()[0]\n' +
      'except Exception as e: res[\'safety_overrides\'] = str(e)\n' +
      'conn.close()\n' +
      'print(json.dumps(res))\n' +
      '"').toString();
  } catch (err) {
    dbResult = `Database check failed: ${err.message}`;
  }
  console.log(`[Validation] Database statistics: ${dbResult}`);

  // Close app
  await app.close();

  // Save gathered test metadata to file for reporting
  const metadata = {
    consoleLogs,
    pageErrors,
    networkRequests,
    networkResponses,
    hardware: { cpu: cpuText, ram: ramText, disk: diskText },
    sysInfoHtml,
    coherence: coherenceText,
    recipeCardsCount,
    logBoxTextLength: logBoxText.length,
    database: JSON.parse(dbResult.trim())
  };
  fs.writeFileSync(path.join(ARTIFACT_DIR, 'validation_metadata.json'), JSON.stringify(metadata, null, 2));
  console.log('[Validation] Successfully saved validation metadata.');
  process.exit(0);
})().catch(err => {
  console.error('[Validation] Validation run encountered error:', err);
  process.exit(1);
});
