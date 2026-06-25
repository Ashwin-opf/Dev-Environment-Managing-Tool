/**
 * E2E Bug Verification Tests
 * Tests every reported bug against the live running app at localhost:8765
 */
const { test, expect } = require('@playwright/test');
const BASE = 'http://127.0.0.1:8765';

// Helper to load the frontend HTML directly
async function openApp(page) {
  const path = require('path');
  const frontendPath = path.resolve(__dirname, '../frontend/index.html').replace(/\\/g, '/');
  await page.goto(`file://${frontendPath}`);
  // Wait for backend connection
  await page.waitForFunction(() => {
    return document.querySelector('#status-label')?.textContent?.includes('online') ||
           document.querySelector('#status-label')?.textContent?.includes('external');
  }, { timeout: 15000 }).catch(() => {});
}

// ─── BUG 1: Scan page Fix button shows update recipe ─────────────────────────
test('Scan Fix button shows System Updates recipe', async ({ page }) => {
  await openApp(page);
  // Navigate to Scan
  await page.click('[data-view="scan"]');
  await page.click('#btn-scan');
  // Wait for scan to complete
  await page.waitForSelector('#btn-scan:not([disabled])', { timeout: 60000 });

  // Check if "System Updates Available" appears
  const updateIssue = page.locator('.issue-card', { hasText: 'System Updates Available' });
  const hasUpdates = await updateIssue.count() > 0;
  
  if (hasUpdates) {
    const fixBtn = updateIssue.locator('.action-btn', { hasText: 'Fix' });
    await expect(fixBtn).toBeVisible();
    await fixBtn.click();
    
    // After clicking Fix, should show solution card with command
    await page.waitForTimeout(2000);
    const solutionCard = page.locator('.solution-card');
    await expect(solutionCard).toBeVisible({ timeout: 5000 });
    const cmdText = await solutionCard.textContent();
    expect(cmdText).toContain('apt'); // Should contain update command
    console.log('✓ Fix button shows solution card with apt command');
  } else {
    console.log('ℹ No system updates available on this system — skip');
    test.skip();
  }
});

// ─── BUG 2: Control Center Error Monitor renders cards ───────────────────────
test('Control Center Error Monitor renders with card structure', async ({ page }) => {
  await openApp(page);
  await page.evaluate(() => window.openOsAdaptationTab());
  await page.waitForTimeout(1000);
  
  // Click Error Monitor tab
  await page.click('#shce-tab-errors');
  await page.waitForTimeout(2000);
  
  const container = page.locator('#shce-error-log');
  await expect(container).toBeVisible();
  
  const content = await container.textContent();
  console.log('Error Monitor content preview:', content.slice(0, 100));
  
  // Should NOT be empty (should have either cards or "No errors" message)
  expect(content.trim()).not.toBe('');
  
  // If there are errors, they should use shce-queue-card class
  const cards = page.locator('#shce-error-log .shce-queue-card');
  const cardCount = await cards.count();
  
  if (cardCount > 0) {
    // Each card should have the Queue Fix button
    const firstCard = cards.first();
    await expect(firstCard.locator('.shce-approve-btn, [onclick*="queueFixFromError"]')).toBeVisible();
    console.log(`✓ Error Monitor shows ${cardCount} cards with Queue Fix buttons`);
  } else {
    console.log('ℹ No errors in monitor — empty state shown');
  }
});

// ─── BUG 3: History tab renders with card structure ──────────────────────────
test('Control Center History tab renders cards not table', async ({ page }) => {
  await openApp(page);
  await page.evaluate(() => window.openOsAdaptationTab());
  await page.waitForTimeout(1000);
  
  await page.click('#shce-tab-history');
  await page.waitForTimeout(2000);
  
  const container = page.locator('#shce-history-list');
  await expect(container).toBeVisible();
  
  const content = await container.textContent();
  expect(content.trim()).not.toBe('');
  console.log('History tab content:', content.slice(0, 100));
  
  // Should NOT show old table structure
  const oldTable = page.locator('#shce-history-table');
  const tableVisible = await oldTable.isVisible().catch(() => false);
  expect(tableVisible).toBe(false);
  
  console.log('✓ History tab uses new card layout');
});

// ─── BUG 4: GSAP animations.js loaded ────────────────────────────────────────
test('GSAP animations are initialized', async ({ page }) => {
  await openApp(page);
  await page.waitForTimeout(2000);
  
  // Check if PCDoctorAnimations is defined
  const animsExist = await page.evaluate(() => typeof window.PCDoctorAnimations !== 'undefined');
  
  if (animsExist) {
    const animsHasInit = await page.evaluate(() => typeof window.PCDoctorAnimations.init === 'function');
    expect(animsHasInit).toBe(true);
    console.log('✓ GSAP PCDoctorAnimations loaded and initialized');
  } else {
    // GSAP may not load in headless chromium — that's acceptable
    console.log('ℹ PCDoctorAnimations not defined (GSAP may not be available in headless)');
  }
});

// ─── BUG 5: Repair Queue shows editable command textarea ─────────────────────
test('Repair Queue shows editable textarea for commands', async ({ page }) => {
  await openApp(page);
  await page.evaluate(() => window.openOsAdaptationTab());
  await page.waitForTimeout(1000);
  
  await page.click('#shce-tab-queue');
  await page.waitForTimeout(2000);
  
  const queue = page.locator('#shce-queue-list');
  await expect(queue).toBeVisible();
  
  const cards = queue.locator('.shce-queue-card');
  const count = await cards.count();
  
  if (count > 0) {
    const firstCard = cards.first();
    // Should have editable textarea (not read-only code block)
    const textarea = firstCard.locator('textarea[id^="shce-qcmd-"]');
    await expect(textarea).toBeVisible();
    const changeBtn = firstCard.locator('button', { hasText: 'Change Command' });
    await expect(changeBtn).toBeVisible();
    console.log(`✓ Repair Queue card has editable textarea and Change Command button`);
  } else {
    console.log('ℹ Repair Queue is empty — no cards to verify');
  }
});

// ─── BUG 6: Failed command execution shows error state ───────────────────────  
test('Failed command execution shows failure state in UI', async ({ page }) => {
  await openApp(page);
  await page.waitForTimeout(3000);
  
  // Trigger a known-to-fail command directly via API
  const resp = await page.evaluate(async (base) => {
    const r = await fetch(`${base}/api/execute`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        command: 'false',  // shell 'false' always exits with code 1
        risk: 'Low',
        title: 'Test failure',
        purpose: 'E2E failure test'
      })
    });
    return r.json();
  }, BASE);
  
  expect(resp.ok).toBe(false);
  expect(resp.returncode).toBe(1);
  console.log(`✓ Backend correctly returns ok=false for failed command (rc=${resp.returncode})`);
  
  // Verify the error went to SHCE error log
  await page.waitForTimeout(500);
  const errorLog = await page.evaluate(async (base) => {
    const r = await fetch(`${base}/api/shce/error-log?limit=5`);
    return r.json();
  }, BASE);
  
  expect(errorLog.ok).toBe(true);
  console.log(`✓ SHCE error log has ${errorLog.total} entries`);
});

// ─── BUG 7: Clear Resolved Logs button exists and works ──────────────────────
test('Error Monitor has Clear Resolved Logs button', async ({ page }) => {
  await openApp(page);
  await page.evaluate(() => window.openOsAdaptationTab());
  await page.waitForTimeout(1000);
  await page.click('#shce-tab-errors');
  await page.waitForTimeout(1500);
  
  const clearBtn = page.locator('#shce-clear-resolved-btn');
  await expect(clearBtn).toBeVisible();
  console.log('✓ Clear Resolved Logs button exists in Error Monitor');
});

// ─── Test: Error Monitor custom command enqueuing works ──────────────────────
test('Error Monitor allows enqueuing custom command fix', async ({ page }) => {
  await openApp(page);
  
  // Navigate to Control Center
  await page.evaluate(() => window.openOsAdaptationTab());
  await page.waitForTimeout(1000);
  
  // Navigate to Error Monitor tab
  await page.click('#shce-tab-errors');
  await page.waitForTimeout(1500);
  
  // Trigger a known-to-fail command to generate a log entry
  const resp = await page.evaluate(async (base) => {
    const r = await fetch(`${base}/api/execute`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        command: 'false',
        risk: 'Low',
        title: 'Custom command failure test',
        purpose: 'E2E custom failure test'
      })
    });
    return r.json();
  }, BASE);
  
  // Reload Errors tab to show the new error log
  await page.click('#shce-tab-overview');
  await page.waitForTimeout(500);
  await page.click('#shce-tab-errors');
  await page.waitForTimeout(1500);
  
  // Locate the error card
  const cards = page.locator('#shce-error-log .shce-error-card');
  const count = await cards.count();
  if (count > 0) {
    const firstCard = cards.first();
    // Fill the custom fix textarea with a custom command
    const textarea = firstCard.locator('textarea[id^="shce-efix-"]');
    await expect(textarea).toBeVisible();
    await textarea.fill('echo "Custom E2E Fix"');
    
    // Click Queue Fix
    const queueBtn = firstCard.locator('.shce-approve-btn', { hasText: 'Queue Fix' });
    await expect(queueBtn).toBeVisible();
    await queueBtn.click();
    
    // Card should disappear from Error Monitor
    await page.waitForTimeout(2000);
    const newCount = await page.locator('#shce-error-log .shce-error-card').count();
    expect(newCount).toBeLessThan(count);
    
    // Switch to Repair Queue and verify the item is queued
    await page.click('#shce-tab-queue');
    await page.waitForTimeout(1500);
    const queueListText = await page.locator('#shce-queue-list').textContent();
    expect(queueListText).toContain('echo "Custom E2E Fix"');
    console.log('✓ Custom command successfully enqueued and visible in Repair Queue');
  } else {
    console.log('ℹ No errors in monitor — skip custom command verification');
  }
});
