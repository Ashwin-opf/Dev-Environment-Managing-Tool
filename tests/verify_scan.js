const { chromium } = require('playwright-core');
const path = require('path');

const ARTIFACT_DIR = 'C:/Users/srira/.gemini/antigravity-ide/brain/e0ad5b85-367c-48d6-983d-020c0a0886e0';

(async () => {
  const browser = await chromium.launch({
    executablePath: 'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe',
    headless: true
  });
  const page = await browser.newPage({ viewport: { width: 1440, height: 920 } });
  await page.goto('http://localhost:5173/', { waitUntil: 'networkidle' });

  await page.click('#btn-nav-scan');
  await page.waitForTimeout(500);

  // Click Start Scan
  await page.click('#btn-scan');
  console.log('Scan started...');
  
  // Wait for scan results container to render issues or complete
  await page.waitForTimeout(4000);

  await page.screenshot({ path: path.join(ARTIFACT_DIR, 'verify_5_scan_results.png') });
  console.log('Scan screenshot captured!');

  await browser.close();
})();
