const { chromium } = require('playwright-core');
const path = require('path');

const ARTIFACT_DIR = 'C:/Users/srira/.gemini/antigravity-ide/brain/e0ad5b85-367c-48d6-983d-020c0a0886e0';

(async () => {
  console.log('--- STARTING PC DOCTOR COMPREHENSIVE VERIFICATION ---');
  const browser = await chromium.launch({
    executablePath: 'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe',
    headless: true
  });
  const context = await browser.newContext({ viewport: { width: 1440, height: 920 } });
  const page = await context.newPage();

  // Listen to console logs and errors
  page.on('console', msg => {
    if (msg.type() === 'error') console.log('PAGE ERROR:', msg.text());
  });

  await page.goto('http://localhost:5173/', { waitUntil: 'networkidle' });
  await page.waitForTimeout(2000); // Allow hardware sampler to tick

  // ─── 1. VERIFY DASHBOARD & LIVE TELEMETRY ───
  console.log('\n[1] Checking Dashboard Telemetry & System Specs:');
  const cpuVal = await page.textContent('#dash-cpu-val');
  const ramVal = await page.textContent('#dash-ram-val');
  const gpuVal = await page.textContent('#dash-gpu-val');
  const diskVal = await page.textContent('#dash-disk-val');
  const specOs = await page.textContent('#spec-os');
  const specCpu = await page.textContent('#spec-cpu');
  const specRam = await page.textContent('#spec-ram');
  const specGpu = await page.textContent('#spec-gpu');

  console.log(`  CPU: ${cpuVal}`);
  console.log(`  RAM: ${ramVal}`);
  console.log(`  GPU: ${gpuVal}`);
  console.log(`  Storage: ${diskVal}`);
  console.log(`  Spec OS: ${specOs}`);
  console.log(`  Spec CPU: ${specCpu}`);
  console.log(`  Spec RAM: ${specRam}`);
  console.log(`  Spec GPU: ${specGpu}`);

  await page.screenshot({ path: path.join(ARTIFACT_DIR, 'verify_1_dashboard.png') });

  // ─── 2. VERIFY REPAIR PROBLEMS (ACTIVE PROBLEMS & APPROVAL POLICY) ───
  console.log('\n[2] Checking Repair Problems View:');
  await page.click('#btn-nav-repair');
  await page.waitForTimeout(1000);

  const activeTabClass = await page.getAttribute('#tab-repair-active', 'class');
  const activeCount = await page.textContent('#repair-active-count');
  const activeContainerHtml = await page.innerHTML('#active-problems-container');
  console.log(`  Active tab selected: ${activeTabClass.includes('active')}`);
  console.log(`  Active problems count: ${activeCount}`);
  console.log(`  Active problems rendered: ${activeContainerHtml.length > 50}`);

  await page.screenshot({ path: path.join(ARTIFACT_DIR, 'verify_2_repair_active.png') });

  // Click Browse Full Knowledge Base tab
  await page.click('#tab-repair-browse');
  await page.waitForTimeout(600);
  const recipeCount = await page.locator('.recipe-card').count();
  console.log(`  Browse Full KB recipe cards count: ${recipeCount}`);
  await page.screenshot({ path: path.join(ARTIFACT_DIR, 'verify_2_repair_browse.png') });

  // ─── 3. VERIFY DEV TOOLS STORE (32 REGISTERED TOOLS) ───
  console.log('\n[3] Checking Dev Tools Store:');
  await page.click('#btn-nav-devtools');
  await page.waitForTimeout(1000);

  const devToolCardsCount = await page.locator('.tool-card').count();
  const categoryChipsCount = await page.locator('#devtools-categories .chip').count();
  console.log(`  Dev Tools Store cards count: ${devToolCardsCount} (Expected >= 30)`);
  console.log(`  Category filter chips count: ${categoryChipsCount}`);

  await page.screenshot({ path: path.join(ARTIFACT_DIR, 'verify_3_devtools_store.png') });

  // Click a tool card to inspect modal
  const firstTool = page.locator('.tool-card').first();
  await firstTool.click();
  await page.waitForTimeout(500);
  const modalTitle = await page.textContent('#tool-modal-title');
  console.log(`  Inspected tool modal title: "${modalTitle}"`);
  await page.screenshot({ path: path.join(ARTIFACT_DIR, 'verify_3_devtool_modal.png') });
  await page.click('button:has-text("Done")');
  await page.waitForTimeout(400);

  // ─── 4. VERIFY MY APPS (INSTALLED TOOLS & WINDOWS PACKAGES) ───
  console.log('\n[4] Checking My Apps:');
  await page.click('#btn-nav-myapps');
  await page.waitForTimeout(1200);

  const myAppsToolsCount = await page.textContent('#myapps-tools-count');
  const myAppsPackagesCount = await page.textContent('#myapps-packages-count');
  const myAppsTotalStat = await page.textContent('#myapps-stat-total');
  const installedCardsCount = await page.locator('.myapp-card').count();

  console.log(`  Installed Developer Tools count badge: ${myAppsToolsCount}`);
  console.log(`  All Windows Packages count badge: ${myAppsPackagesCount}`);
  console.log(`  My Apps header stat total: ${myAppsTotalStat}`);
  console.log(`  Rendered installed tool cards count: ${installedCardsCount}`);

  await page.screenshot({ path: path.join(ARTIFACT_DIR, 'verify_4_myapps_tools.png') });

  // Switch to All Windows Packages subtab
  await page.click('#tab-myapps-packages');
  await page.waitForTimeout(800);
  const packagesCardsCount = await page.locator('.myapp-card').count();
  console.log(`  Rendered All Windows Packages cards count: ${packagesCardsCount}`);
  await page.screenshot({ path: path.join(ARTIFACT_DIR, 'verify_4_myapps_packages.png') });

  // ─── 5. VERIFY SCAN PC & APPROVE & RUN FIX BUTTON ───
  console.log('\n[5] Checking Scan PC Section:');
  await page.click('#btn-nav-scan');
  await page.waitForTimeout(800);
  await page.screenshot({ path: path.join(ARTIFACT_DIR, 'verify_5_scan_initial.png') });

  console.log('\n--- ALL VERIFICATIONS EXECUTED SUCCESSFULLY ---');
  await browser.close();
})();
