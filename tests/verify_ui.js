const { chromium } = require('playwright-core');

(async () => {
  const browser = await chromium.launch({
    executablePath: 'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe',
    headless: true
  });
  const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
  
  await page.goto('http://localhost:5173/', { waitUntil: 'networkidle' });
  await page.waitForTimeout(1000);

  // 1. Dark Theme Dashboard
  await page.screenshot({ path: 'C:/Users/srira/.gemini/antigravity-ide/brain/e0ad5b85-367c-48d6-983d-020c0a0886e0/screenshot_dark_dashboard.png' });

  // 2. Open Tool Modal on DevTools
  await page.click('#btn-nav-devtools');
  await page.waitForTimeout(800);
  const toolCard = await page.waitForSelector('.tool-card');
  await toolCard.click();
  await page.waitForTimeout(400);
  await page.screenshot({ path: 'C:/Users/srira/.gemini/antigravity-ide/brain/e0ad5b85-367c-48d6-983d-020c0a0886e0/screenshot_tool_modal.png' });
  await page.click('button:has-text("Done")');
  await page.waitForTimeout(400);

  // 3. Switch to Light Mode
  await page.click('#theme-toggle-btn');
  await page.waitForTimeout(500);

  // 4. View My Apps in Light Mode
  await page.click('#btn-nav-myapps');
  await page.waitForTimeout(1000);
  await page.screenshot({ path: 'C:/Users/srira/.gemini/antigravity-ide/brain/e0ad5b85-367c-48d6-983d-020c0a0886e0/test_screenshot.png' });

  // 5. View Repair Tab with Dynamic KB pending banner in Light Mode
  await page.click('#btn-nav-repair');
  await page.waitForTimeout(800);
  await page.screenshot({ path: 'C:/Users/srira/.gemini/antigravity-ide/brain/e0ad5b85-367c-48d6-983d-020c0a0886e0/screenshot_repair_tab.png' });

  console.log('PLAYWRIGHT TESTS COMPLETED SUCCESSFULLY');
  await browser.close();
})();
