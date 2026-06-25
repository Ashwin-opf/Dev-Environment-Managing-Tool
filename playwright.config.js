const { devices } = require('@playwright/test');

/** @type {import('@playwright/test').PlaywrightTestConfig} */
module.exports = {
  testDir: 'tests',
  timeout: 120000,
  retries: 0,
  workers: 2,
  reporter: [['list']],
  projects: [
    {
      name: 'chromium',
      use: {
        browserName: 'chromium',
        headless: true,
        viewport: { width: 1280, height: 820 },
        launchOptions: {
          args: [
            '--allow-file-access-from-files',
            '--no-sandbox',
            '--disable-setuid-sandbox',
            '--disable-gpu-sandbox',
            '--disable-seccomp-filter-sandbox'
          ]
        }
      },
    },
  ],
};
